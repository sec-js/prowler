import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from allauth.socialaccount.models import SocialLogin
from django.conf import settings
from django.db import connection as django_connection
from django.db import connections as django_connections
from django.urls import reverse
from django_celery_results.models import TaskResult
from rest_framework import status
from rest_framework.test import APIClient
from tasks.jobs.backfill import backfill_resource_scan_summaries

from api.db_utils import rls_transaction
from api.models import (
    ComplianceOverview,
    ComplianceRequirementOverview,
    Finding,
    Integration,
    IntegrationProviderRelationship,
    Invitation,
    LighthouseConfiguration,
    Membership,
    Processor,
    Provider,
    ProviderGroup,
    ProviderSecret,
    Resource,
    ResourceTag,
    ResourceTagMapping,
    Role,
    SAMLConfiguration,
    SAMLDomainIndex,
    Scan,
    ScanSummary,
    StateChoices,
    StatusChoices,
    Task,
    User,
    UserRoleRelationship,
)
from api.rls import Tenant
from api.v1.serializers import TokenSerializer
from prowler.lib.check.models import Severity
from prowler.lib.outputs.finding import Status

TODAY = str(datetime.today().date())
API_JSON_CONTENT_TYPE = "application/vnd.api+json"
NO_TENANT_HTTP_STATUS = status.HTTP_401_UNAUTHORIZED
TEST_USER = "dev@prowler.com"
TEST_PASSWORD = "testing_psswd"


def today_after_n_days(n_days: int) -> str:
    return datetime.strftime(
        datetime.today().date() + timedelta(days=n_days), "%Y-%m-%d"
    )


@pytest.fixture(scope="module")
def enforce_test_user_db_connection(django_db_setup, django_db_blocker):
    """Ensure tests use the test user for database connections."""
    test_user = "test"
    test_password = "test"

    with django_db_blocker.unblock():
        with django_connection.cursor() as cursor:
            # Required for testing purposes using APIClient
            cursor.execute(f"GRANT ALL PRIVILEGES ON django_session TO {test_user};")

        original_user = settings.DATABASES["default"]["USER"]
        original_password = settings.DATABASES["default"]["PASSWORD"]

        django_connections["default"].settings_dict["USER"] = test_user
        django_connections["default"].settings_dict["PASSWORD"] = test_password

        django_connections["default"].close()
        django_connections["default"].connect()

    yield

    with django_db_blocker.unblock():
        django_connections["default"].settings_dict["USER"] = original_user
        django_connections["default"].settings_dict["PASSWORD"] = original_password

        django_connections["default"].close()
        django_connections["default"].connect()


@pytest.fixture(autouse=True)
def disable_logging():
    logging.disable(logging.CRITICAL)


@pytest.fixture(scope="session", autouse=True)
def create_test_user(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        user = User.objects.create_user(
            name="testing",
            email=TEST_USER,
            password=TEST_PASSWORD,
        )
    return user


@pytest.fixture(scope="function")
def create_test_user_rbac(django_db_setup, django_db_blocker, tenants_fixture):
    with django_db_blocker.unblock():
        user = User.objects.create_user(
            name="testing",
            email="rbac@rbac.com",
            password=TEST_PASSWORD,
        )
        tenant = tenants_fixture[0]
        Membership.objects.create(
            user=user,
            tenant=tenant,
            role=Membership.RoleChoices.OWNER,
        )
        Role.objects.create(
            name="admin",
            tenant_id=tenant.id,
            manage_users=True,
            manage_account=True,
            manage_billing=True,
            manage_providers=True,
            manage_integrations=True,
            manage_scans=True,
            unlimited_visibility=True,
        )
        UserRoleRelationship.objects.create(
            user=user,
            role=Role.objects.get(name="admin"),
            tenant_id=tenant.id,
        )
    return user


@pytest.fixture(scope="function")
def create_test_user_rbac_no_roles(django_db_setup, django_db_blocker, tenants_fixture):
    with django_db_blocker.unblock():
        user = User.objects.create_user(
            name="testing",
            email="rbac_noroles@rbac.com",
            password=TEST_PASSWORD,
        )
        tenant = tenants_fixture[0]
        Membership.objects.create(
            user=user,
            tenant=tenant,
            role=Membership.RoleChoices.OWNER,
        )

    return user


@pytest.fixture(scope="function")
def create_test_user_rbac_limited(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        user = User.objects.create_user(
            name="testing_limited",
            email="rbac_limited@rbac.com",
            password=TEST_PASSWORD,
        )
        tenant = Tenant.objects.create(
            name="Tenant Test",
        )
        Membership.objects.create(
            user=user,
            tenant=tenant,
            role=Membership.RoleChoices.OWNER,
        )
        Role.objects.create(
            name="limited",
            tenant_id=tenant.id,
            manage_users=False,
            manage_account=False,
            manage_billing=False,
            manage_providers=False,
            manage_integrations=False,
            manage_scans=False,
            unlimited_visibility=False,
        )
        UserRoleRelationship.objects.create(
            user=user,
            role=Role.objects.get(name="limited"),
            tenant_id=tenant.id,
        )
    return user


@pytest.fixture
def authenticated_client_rbac(create_test_user_rbac, tenants_fixture, client):
    client.user = create_test_user_rbac
    tenant_id = tenants_fixture[0].id
    serializer = TokenSerializer(
        data={
            "type": "tokens",
            "email": "rbac@rbac.com",
            "password": TEST_PASSWORD,
            "tenant_id": tenant_id,
        }
    )
    serializer.is_valid(raise_exception=True)
    access_token = serializer.validated_data["access"]
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {access_token}"
    return client


@pytest.fixture
def authenticated_client_rbac_noroles(
    create_test_user_rbac_no_roles, tenants_fixture, client
):
    client.user = create_test_user_rbac_no_roles
    serializer = TokenSerializer(
        data={
            "type": "tokens",
            "email": "rbac_noroles@rbac.com",
            "password": TEST_PASSWORD,
        }
    )
    serializer.is_valid()
    access_token = serializer.validated_data["access"]
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {access_token}"
    return client


@pytest.fixture
def authenticated_client_no_permissions_rbac(
    create_test_user_rbac_limited, tenants_fixture, client
):
    client.user = create_test_user_rbac_limited
    serializer = TokenSerializer(
        data={
            "type": "tokens",
            "email": "rbac_limited@rbac.com",
            "password": TEST_PASSWORD,
        }
    )
    serializer.is_valid()
    access_token = serializer.validated_data["access"]
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {access_token}"
    return client


@pytest.fixture
def authenticated_client(
    create_test_user, tenants_fixture, set_user_admin_roles_fixture, client
):
    client.user = create_test_user
    serializer = TokenSerializer(
        data={"type": "tokens", "email": TEST_USER, "password": TEST_PASSWORD}
    )
    serializer.is_valid()
    access_token = serializer.validated_data["access"]
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {access_token}"
    return client


@pytest.fixture
def authenticated_api_client(create_test_user, tenants_fixture):
    client = APIClient()
    serializer = TokenSerializer(
        data={"type": "tokens", "email": TEST_USER, "password": TEST_PASSWORD}
    )
    serializer.is_valid()
    access_token = serializer.validated_data["access"]
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {access_token}"

    return client


@pytest.fixture
def tenants_fixture(create_test_user):
    user = create_test_user
    tenant1 = Tenant.objects.create(
        name="Tenant One",
    )
    Membership.objects.create(
        user=user,
        tenant=tenant1,
    )
    tenant2 = Tenant.objects.create(
        name="Tenant Two",
    )
    Membership.objects.create(
        user=user,
        tenant=tenant2,
        role=Membership.RoleChoices.OWNER,
    )
    tenant3 = Tenant.objects.create(
        name="Tenant Three",
    )

    return tenant1, tenant2, tenant3


@pytest.fixture
def set_user_admin_roles_fixture(create_test_user, tenants_fixture):
    user = create_test_user
    for tenant in tenants_fixture[:2]:
        with rls_transaction(str(tenant.id)):
            role = Role.objects.create(
                name="admin",
                tenant_id=tenant.id,
                manage_users=True,
                manage_account=True,
                manage_billing=True,
                manage_providers=True,
                manage_integrations=True,
                manage_scans=True,
                unlimited_visibility=True,
            )
            UserRoleRelationship.objects.create(
                user=user,
                role=role,
                tenant_id=tenant.id,
            )


@pytest.fixture
def invitations_fixture(create_test_user, tenants_fixture):
    user = create_test_user
    tenant = tenants_fixture[0]
    valid_invitation = Invitation.objects.create(
        email="testing@prowler.com",
        state=Invitation.State.PENDING,
        token="TESTING1234567",
        inviter=user,
        tenant=tenant,
    )
    expired_invitation = Invitation.objects.create(
        email="testing@prowler.com",
        state=Invitation.State.EXPIRED,
        token="TESTING1234568",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        inviter=user,
        tenant=tenant,
    )
    return valid_invitation, expired_invitation


@pytest.fixture
def users_fixture(django_user_model):
    user1 = User.objects.create_user(
        name="user1", email="test_unit0@prowler.com", password="S3cret"
    )
    user2 = User.objects.create_user(
        name="user2", email="test_unit1@prowler.com", password="S3cret"
    )
    user3 = User.objects.create_user(
        name="user3", email="test_unit2@prowler.com", password="S3cret"
    )
    return user1, user2, user3


@pytest.fixture
def providers_fixture(tenants_fixture):
    tenant, *_ = tenants_fixture
    provider1 = Provider.objects.create(
        provider="aws",
        uid="123456789012",
        alias="aws_testing_1",
        tenant_id=tenant.id,
    )
    provider2 = Provider.objects.create(
        provider="aws",
        uid="123456789013",
        alias="aws_testing_2",
        tenant_id=tenant.id,
    )
    provider3 = Provider.objects.create(
        provider="gcp",
        uid="a12322-test321",
        alias="gcp_testing",
        tenant_id=tenant.id,
    )
    provider4 = Provider.objects.create(
        provider="kubernetes",
        uid="kubernetes-test-12345",
        alias="k8s_testing",
        tenant_id=tenant.id,
    )
    provider5 = Provider.objects.create(
        provider="azure",
        uid="37b065f8-26b0-4218-a665-0b23d07b27d9",
        alias="azure_testing",
        tenant_id=tenant.id,
        scanner_args={"key1": "value1", "key2": {"key21": "value21"}},
    )
    provider6 = Provider.objects.create(
        provider="m365",
        uid="m365.test.com",
        alias="m365_testing",
        tenant_id=tenant.id,
    )

    return provider1, provider2, provider3, provider4, provider5, provider6


@pytest.fixture
def processor_fixture(tenants_fixture):
    tenant, *_ = tenants_fixture
    processor = Processor.objects.create(
        tenant_id=tenant.id,
        processor_type="mutelist",
        configuration="Mutelist:\n  Accounts:\n    *:\n      Checks:\n        iam_user_hardware_mfa_enabled:\n         "
        " Regions:\n            - *\n          Resources:\n            - *",
    )

    return processor


@pytest.fixture
def provider_groups_fixture(tenants_fixture):
    tenant, *_ = tenants_fixture
    pgroup1 = ProviderGroup.objects.create(
        name="Group One",
        tenant_id=tenant.id,
    )
    pgroup2 = ProviderGroup.objects.create(
        name="Group Two",
        tenant_id=tenant.id,
    )
    pgroup3 = ProviderGroup.objects.create(
        name="Group Three",
        tenant_id=tenant.id,
    )

    return pgroup1, pgroup2, pgroup3


@pytest.fixture
def admin_role_fixture(tenants_fixture):
    tenant, *_ = tenants_fixture

    return Role.objects.get_or_create(
        name="admin",
        tenant_id=tenant.id,
        manage_users=True,
        manage_account=True,
        manage_billing=True,
        manage_providers=True,
        manage_integrations=True,
        manage_scans=True,
        unlimited_visibility=True,
    )[0]


@pytest.fixture
def roles_fixture(tenants_fixture):
    tenant, *_ = tenants_fixture
    role1 = Role.objects.create(
        name="Role One",
        tenant_id=tenant.id,
        manage_users=True,
        manage_account=True,
        manage_billing=True,
        manage_providers=True,
        manage_integrations=False,
        manage_scans=True,
        unlimited_visibility=False,
    )
    role2 = Role.objects.create(
        name="Role Two",
        tenant_id=tenant.id,
        manage_users=False,
        manage_account=False,
        manage_billing=False,
        manage_providers=True,
        manage_integrations=True,
        manage_scans=True,
        unlimited_visibility=True,
    )
    role3 = Role.objects.create(
        name="Role Three",
        tenant_id=tenant.id,
        manage_users=True,
        manage_account=True,
        manage_billing=True,
        manage_providers=True,
        manage_integrations=True,
        manage_scans=True,
        unlimited_visibility=True,
    )
    role4 = Role.objects.create(
        name="Role Four",
        tenant_id=tenant.id,
        manage_users=False,
        manage_account=False,
        manage_billing=False,
        manage_providers=False,
        manage_integrations=False,
        manage_scans=False,
        unlimited_visibility=False,
    )

    return role1, role2, role3, role4


@pytest.fixture
def provider_secret_fixture(providers_fixture):
    return tuple(
        ProviderSecret.objects.create(
            tenant_id=provider.tenant_id,
            provider=provider,
            secret_type=ProviderSecret.TypeChoices.STATIC,
            secret={"key": "value"},
            name=provider.alias,
        )
        for provider in providers_fixture
    )


@pytest.fixture
def scans_fixture(tenants_fixture, providers_fixture):
    tenant, *_ = tenants_fixture
    provider, provider2, *_ = providers_fixture

    scan1 = Scan.objects.create(
        name="Scan 1",
        provider=provider,
        trigger=Scan.TriggerChoices.MANUAL,
        state=StateChoices.COMPLETED,
        tenant_id=tenant.id,
        started_at="2024-01-02T00:00:00Z",
    )
    scan2 = Scan.objects.create(
        name="Scan 2",
        provider=provider,
        trigger=Scan.TriggerChoices.SCHEDULED,
        state=StateChoices.FAILED,
        tenant_id=tenant.id,
        started_at="2024-01-02T00:00:00Z",
    )
    scan3 = Scan.objects.create(
        name="Scan 3",
        provider=provider2,
        trigger=Scan.TriggerChoices.SCHEDULED,
        state=StateChoices.AVAILABLE,
        tenant_id=tenant.id,
        started_at="2024-01-02T00:00:00Z",
    )
    return scan1, scan2, scan3


@pytest.fixture
def tasks_fixture(tenants_fixture):
    tenant, *_ = tenants_fixture

    task_runner_task1 = TaskResult.objects.create(
        task_id="81a1b34b-ff6e-498e-979c-d6a83260167f",
        task_name="task_runner_task1",
        task_kwargs='{"kwarg1": "value1"}',
        status="SUCCESS",
    )
    task_runner_task2 = TaskResult.objects.create(
        task_id="4d0260a5-2e1f-4a34-a976-8c5acb9f5499",
        task_name="task_runner_task1",
        status="PENDING",
    )
    task1 = Task.objects.create(
        id=task_runner_task1.task_id,
        task_runner_task=task_runner_task1,
        tenant_id=tenant.id,
    )
    task2 = Task.objects.create(
        id=task_runner_task2.task_id,
        task_runner_task=task_runner_task2,
        tenant_id=tenant.id,
    )

    return task1, task2


@pytest.fixture
def resources_fixture(providers_fixture):
    provider, *_ = providers_fixture

    tags = [
        ResourceTag.objects.create(
            tenant_id=provider.tenant_id,
            key="key",
            value="value",
        ),
        ResourceTag.objects.create(
            tenant_id=provider.tenant_id,
            key="key2",
            value="value2",
        ),
    ]

    resource1 = Resource.objects.create(
        tenant_id=provider.tenant_id,
        provider=provider,
        uid="arn:aws:ec2:us-east-1:123456789012:instance/i-1234567890abcdef0",
        name="My Instance 1",
        region="us-east-1",
        service="ec2",
        type="prowler-test",
    )

    resource1.upsert_or_delete_tags(tags)

    resource2 = Resource.objects.create(
        tenant_id=provider.tenant_id,
        provider=provider,
        uid="arn:aws:ec2:us-east-1:123456789012:instance/i-1234567890abcdef1",
        name="My Instance 2",
        region="eu-west-1",
        service="s3",
        type="prowler-test",
    )
    resource2.upsert_or_delete_tags(tags)

    resource3 = Resource.objects.create(
        tenant_id=providers_fixture[1].tenant_id,
        provider=providers_fixture[1],
        uid="arn:aws:ec2:us-east-1:123456789012:bucket/i-1234567890abcdef2",
        name="My Bucket 3",
        region="us-east-1",
        service="ec2",
        type="test",
    )

    tags = [
        ResourceTag.objects.create(
            tenant_id=provider.tenant_id,
            key="key3",
            value="multi word value3",
        ),
    ]
    resource3.upsert_or_delete_tags(tags)

    return resource1, resource2, resource3


@pytest.fixture
def findings_fixture(scans_fixture, resources_fixture):
    scan, *_ = scans_fixture
    resource1, resource2, *_ = resources_fixture

    finding1 = Finding.objects.create(
        tenant_id=scan.tenant_id,
        uid="test_finding_uid_1",
        scan=scan,
        delta=None,
        status=Status.FAIL,
        status_extended="test status extended ",
        impact=Severity.critical,
        impact_extended="test impact extended one",
        severity=Severity.critical,
        raw_result={
            "status": Status.FAIL,
            "impact": Severity.critical,
            "severity": Severity.critical,
        },
        tags={"test": "dev-qa"},
        check_id="test_check_id",
        check_metadata={
            "CheckId": "test_check_id",
            "Description": "test description apple sauce",
            "servicename": "ec2",
        },
        first_seen_at="2024-01-02T00:00:00Z",
    )

    finding1.add_resources([resource1])

    finding2 = Finding.objects.create(
        tenant_id=scan.tenant_id,
        uid="test_finding_uid_2",
        scan=scan,
        delta="new",
        status=Status.FAIL,
        status_extended="Load Balancer exposed to internet",
        impact=Severity.medium,
        impact_extended="test impact extended two",
        severity=Severity.medium,
        raw_result={
            "status": Status.FAIL,
            "impact": Severity.medium,
            "severity": Severity.medium,
        },
        tags={"test": "test"},
        check_id="test_check_id",
        check_metadata={
            "CheckId": "test_check_id",
            "Description": "test description orange juice",
            "servicename": "s3",
        },
        first_seen_at="2024-01-02T00:00:00Z",
        muted=True,
    )

    finding2.add_resources([resource2])

    return finding1, finding2


@pytest.fixture
def compliance_overviews_fixture(scans_fixture, tenants_fixture):
    tenant = tenants_fixture[0]
    scan1, scan2, scan3 = scans_fixture

    compliance_overview1 = ComplianceOverview.objects.create(
        tenant=tenant,
        scan=scan1,
        compliance_id="aws_account_security_onboarding_aws",
        framework="AWS-Account-Security-Onboarding",
        version="1.0",
        description="Description for AWS Account Security Onboarding",
        region="eu-west-1",
        requirements={
            "requirement1": {
                "name": "Requirement 1",
                "checks": {"check1.1": "PASS", "check1.2": None},
                "status": "PASS",
                "attributes": [],
                "description": "Description of requirement 1",
                "checks_status": {
                    "total": 2,
                    "failed": 0,
                    "passed": 2,
                },
            },
            "requirement2": {
                "name": "Requirement 2",
                "checks": {"check2.1": "PASS", "check2.2": "PASS"},
                "status": "PASS",
                "attributes": [],
                "description": "Description of requirement 2",
                "checks_status": {
                    "total": 2,
                    "failed": 0,
                    "passed": 2,
                },
            },
            "requirement3": {
                "name": "Requirement 3 - manual",
                "checks": {},
                "status": "PASS",
                "attributes": [],
                "description": "Description of requirement 2",
                "checks_status": {
                    "total": 0,
                    "failed": 0,
                    "passed": 0,
                },
            },
        },
        requirements_passed=2,
        requirements_failed=0,
        requirements_manual=1,
        total_requirements=3,
    )

    compliance_overview2 = ComplianceOverview.objects.create(
        tenant=tenant,
        scan=scan1,
        compliance_id="aws_account_security_onboarding_aws",
        framework="AWS-Account-Security-Onboarding",
        version="1.0",
        description="Description for AWS Account Security Onboarding",
        region="eu-west-2",
        requirements={
            "requirement1": {
                "name": "Requirement 1",
                "checks": {"check1.1": "PASS", "check1.2": None},
                "status": "PASS",
                "attributes": [],
                "description": "Description of requirement 1",
                "checks_status": {
                    "total": 2,
                    "failed": 0,
                    "passed": 2,
                },
            },
            "requirement2": {
                "name": "Requirement 2",
                "checks": {"check2.1": "PASS", "check2.2": "FAIL"},
                "status": "FAIL",
                "attributes": [],
                "description": "Description of requirement 2",
                "checks_status": {
                    "total": 2,
                    "failed": 1,
                    "passed": 1,
                },
            },
            "requirement3": {
                "name": "Requirement 3 - manual",
                "checks": {},
                "status": "PASS",
                "attributes": [],
                "description": "Description of requirement 2",
                "checks_status": {
                    "total": 0,
                    "failed": 0,
                    "passed": 0,
                },
            },
        },
        requirements_passed=1,
        requirements_failed=1,
        requirements_manual=1,
        total_requirements=3,
    )

    # Return the created compliance overviews
    return compliance_overview1, compliance_overview2


@pytest.fixture
def compliance_requirements_overviews_fixture(scans_fixture, tenants_fixture):
    """Fixture for ComplianceRequirementOverview objects used by the new ComplianceOverviewViewSet."""
    tenant = tenants_fixture[0]
    scan1, scan2, scan3 = scans_fixture

    # Create ComplianceRequirementOverview objects for scan1
    requirement_overview1 = ComplianceRequirementOverview.objects.create(
        tenant=tenant,
        scan=scan1,
        compliance_id="aws_account_security_onboarding_aws",
        framework="AWS-Account-Security-Onboarding",
        version="1.0",
        description="Description for AWS Account Security Onboarding",
        region="eu-west-1",
        requirement_id="requirement1",
        requirement_status=StatusChoices.PASS,
        passed_checks=2,
        failed_checks=0,
        total_checks=2,
    )

    requirement_overview2 = ComplianceRequirementOverview.objects.create(
        tenant=tenant,
        scan=scan1,
        compliance_id="aws_account_security_onboarding_aws",
        framework="AWS-Account-Security-Onboarding",
        version="1.0",
        description="Description for AWS Account Security Onboarding",
        region="eu-west-1",
        requirement_id="requirement2",
        requirement_status=StatusChoices.PASS,
        passed_checks=2,
        failed_checks=0,
        total_checks=2,
    )

    requirement_overview3 = ComplianceRequirementOverview.objects.create(
        tenant=tenant,
        scan=scan1,
        compliance_id="aws_account_security_onboarding_aws",
        framework="AWS-Account-Security-Onboarding",
        version="1.0",
        description="Description for AWS Account Security Onboarding",
        region="eu-west-2",
        requirement_id="requirement1",
        requirement_status=StatusChoices.PASS,
        passed_checks=2,
        failed_checks=0,
        total_checks=2,
    )

    requirement_overview4 = ComplianceRequirementOverview.objects.create(
        tenant=tenant,
        scan=scan1,
        compliance_id="aws_account_security_onboarding_aws",
        framework="AWS-Account-Security-Onboarding",
        version="1.0",
        description="Description for AWS Account Security Onboarding",
        region="eu-west-2",
        requirement_id="requirement2",
        requirement_status=StatusChoices.FAIL,
        passed_checks=1,
        failed_checks=1,
        total_checks=2,
    )

    requirement_overview5 = ComplianceRequirementOverview.objects.create(
        tenant=tenant,
        scan=scan1,
        compliance_id="aws_account_security_onboarding_aws",
        framework="AWS-Account-Security-Onboarding",
        version="1.0",
        description="Description for AWS Account Security Onboarding (MANUAL)",
        region="eu-west-2",
        requirement_id="requirement3",
        requirement_status=StatusChoices.MANUAL,
        passed_checks=0,
        failed_checks=0,
        total_checks=0,
    )

    # Create a different compliance framework for testing
    requirement_overview6 = ComplianceRequirementOverview.objects.create(
        tenant=tenant,
        scan=scan1,
        compliance_id="cis_1.4_aws",
        framework="CIS-1.4-AWS",
        version="1.4",
        description="CIS AWS Foundations Benchmark v1.4.0",
        region="eu-west-1",
        requirement_id="cis_requirement1",
        requirement_status=StatusChoices.FAIL,
        passed_checks=0,
        failed_checks=3,
        total_checks=3,
    )

    # Create another compliance framework for testing MITRE ATT&CK
    requirement_overview7 = ComplianceRequirementOverview.objects.create(
        tenant=tenant,
        scan=scan1,
        compliance_id="mitre_attack_aws",
        framework="MITRE-ATTACK",
        version="1.0",
        description="MITRE ATT&CK",
        region="eu-west-1",
        requirement_id="mitre_requirement1",
        requirement_status=StatusChoices.FAIL,
        passed_checks=0,
        failed_checks=0,
        total_checks=0,
    )

    return (
        requirement_overview1,
        requirement_overview2,
        requirement_overview3,
        requirement_overview4,
        requirement_overview5,
        requirement_overview6,
        requirement_overview7,
    )


def get_api_tokens(
    api_client, user_email: str, user_password: str, tenant_id: str = None
) -> tuple[str, str]:
    json_body = {
        "data": {
            "type": "tokens",
            "attributes": {
                "email": user_email,
                "password": user_password,
            },
        }
    }
    if tenant_id is not None:
        json_body["data"]["attributes"]["tenant_id"] = tenant_id
    response = api_client.post(
        reverse("token-obtain"),
        data=json_body,
        format="vnd.api+json",
    )
    return (
        response.json()["data"]["attributes"]["access"],
        response.json()["data"]["attributes"]["refresh"],
    )


@pytest.fixture
def scan_summaries_fixture(tenants_fixture, providers_fixture):
    tenant = tenants_fixture[0]
    provider = providers_fixture[0]
    scan = Scan.objects.create(
        name="overview scan",
        provider=provider,
        trigger=Scan.TriggerChoices.MANUAL,
        state=StateChoices.COMPLETED,
        tenant=tenant,
    )

    ScanSummary.objects.create(
        tenant=tenant,
        check_id="check1",
        service="service1",
        severity="high",
        region="region1",
        _pass=1,
        fail=0,
        muted=0,
        total=1,
        new=1,
        changed=0,
        unchanged=0,
        fail_new=0,
        fail_changed=0,
        pass_new=1,
        pass_changed=0,
        muted_new=0,
        muted_changed=0,
        scan=scan,
    )

    ScanSummary.objects.create(
        tenant=tenant,
        check_id="check1",
        service="service1",
        severity="high",
        region="region2",
        _pass=0,
        fail=1,
        muted=1,
        total=2,
        new=2,
        changed=0,
        unchanged=0,
        fail_new=1,
        fail_changed=0,
        pass_new=0,
        pass_changed=0,
        muted_new=1,
        muted_changed=0,
        scan=scan,
    )

    ScanSummary.objects.create(
        tenant=tenant,
        check_id="check2",
        service="service2",
        severity="critical",
        region="region1",
        _pass=1,
        fail=0,
        muted=0,
        total=1,
        new=1,
        changed=0,
        unchanged=0,
        fail_new=0,
        fail_changed=0,
        pass_new=1,
        pass_changed=0,
        muted_new=0,
        muted_changed=0,
        scan=scan,
    )


@pytest.fixture
def integrations_fixture(providers_fixture):
    provider1, provider2, *_ = providers_fixture
    tenant_id = provider1.tenant_id
    integration1 = Integration.objects.create(
        tenant_id=tenant_id,
        enabled=True,
        connected=True,
        integration_type="amazon_s3",
        configuration={"key": "value"},
        credentials={"psswd": "1234"},
    )
    IntegrationProviderRelationship.objects.create(
        tenant_id=tenant_id,
        integration=integration1,
        provider=provider1,
    )

    integration2 = Integration.objects.create(
        tenant_id=tenant_id,
        enabled=True,
        connected=True,
        integration_type="amazon_s3",
        configuration={"key": "value1"},
        credentials={"psswd": "1234"},
    )
    IntegrationProviderRelationship.objects.create(
        tenant_id=tenant_id,
        integration=integration2,
        provider=provider1,
    )
    IntegrationProviderRelationship.objects.create(
        tenant_id=tenant_id,
        integration=integration2,
        provider=provider2,
    )

    return integration1, integration2


@pytest.fixture
def backfill_scan_metadata_fixture(scans_fixture, findings_fixture):
    for scan_instance in scans_fixture:
        tenant_id = scan_instance.tenant_id
        scan_id = scan_instance.id
        backfill_resource_scan_summaries(tenant_id=tenant_id, scan_id=scan_id)


@pytest.fixture
def lighthouse_config_fixture(authenticated_client, tenants_fixture):
    return LighthouseConfiguration.objects.create(
        tenant_id=tenants_fixture[0].id,
        name="OpenAI",
        api_key_decoded="sk-test1234567890T3BlbkFJtest1234567890",
        model="gpt-4o",
        temperature=0,
        max_tokens=4000,
        business_context="Test business context",
        is_active=True,
    )


@pytest.fixture(scope="function")
def latest_scan_finding(authenticated_client, providers_fixture, resources_fixture):
    provider = providers_fixture[0]
    tenant_id = str(providers_fixture[0].tenant_id)
    resource = resources_fixture[0]
    scan = Scan.objects.create(
        name="latest completed scan",
        provider=provider,
        trigger=Scan.TriggerChoices.MANUAL,
        state=StateChoices.COMPLETED,
        tenant_id=tenant_id,
    )
    finding = Finding.objects.create(
        tenant_id=tenant_id,
        uid="test_finding_uid_1",
        scan=scan,
        delta="new",
        status=Status.FAIL,
        status_extended="test status extended ",
        impact=Severity.critical,
        impact_extended="test impact extended one",
        severity=Severity.critical,
        raw_result={
            "status": Status.FAIL,
            "impact": Severity.critical,
            "severity": Severity.critical,
        },
        tags={"test": "dev-qa"},
        check_id="test_check_id",
        check_metadata={
            "CheckId": "test_check_id",
            "Description": "test description apple sauce",
        },
        first_seen_at="2024-01-02T00:00:00Z",
    )

    finding.add_resources([resource])
    backfill_resource_scan_summaries(tenant_id, str(scan.id))
    return finding


@pytest.fixture(scope="function")
def latest_scan_resource(authenticated_client, providers_fixture):
    provider = providers_fixture[0]
    tenant_id = str(providers_fixture[0].tenant_id)
    scan = Scan.objects.create(
        name="latest completed scan for resource",
        provider=provider,
        trigger=Scan.TriggerChoices.MANUAL,
        state=StateChoices.COMPLETED,
        tenant_id=tenant_id,
    )
    resource = Resource.objects.create(
        tenant_id=tenant_id,
        provider=provider,
        uid="latest_resource_uid",
        name="Latest Resource",
        region="us-east-1",
        service="ec2",
        type="instance",
        metadata='{"test": "metadata"}',
        details='{"test": "details"}',
    )

    resource_tag = ResourceTag.objects.create(
        tenant_id=tenant_id,
        key="environment",
        value="test",
    )
    ResourceTagMapping.objects.create(
        tenant_id=tenant_id,
        resource=resource,
        tag=resource_tag,
    )

    finding = Finding.objects.create(
        tenant_id=tenant_id,
        uid="test_finding_uid_latest",
        scan=scan,
        delta="new",
        status=Status.FAIL,
        status_extended="test status extended ",
        impact=Severity.critical,
        impact_extended="test impact extended",
        severity=Severity.critical,
        raw_result={
            "status": Status.FAIL,
            "impact": Severity.critical,
            "severity": Severity.critical,
        },
        tags={"test": "latest"},
        check_id="test_check_id_latest",
        check_metadata={
            "CheckId": "test_check_id_latest",
            "Description": "test description latest",
        },
        first_seen_at="2024-01-02T00:00:00Z",
    )
    finding.add_resources([resource])

    backfill_resource_scan_summaries(tenant_id, str(scan.id))
    return resource


@pytest.fixture
def saml_setup(tenants_fixture):
    tenant_id = tenants_fixture[0].id
    domain = "prowler.com"

    SAMLDomainIndex.objects.create(email_domain=domain, tenant_id=tenant_id)

    metadata_xml = """<?xml version='1.0' encoding='UTF-8'?>
    <md:EntityDescriptor entityID='TEST' xmlns:md='urn:oasis:names:tc:SAML:2.0:metadata'>
    <md:IDPSSODescriptor WantAuthnRequestsSigned='false' protocolSupportEnumeration='urn:oasis:names:tc:SAML:2.0:protocol'>
        <md:KeyDescriptor use='signing'>
        <ds:KeyInfo xmlns:ds='http://www.w3.org/2000/09/xmldsig#'>
            <ds:X509Data>
            <ds:X509Certificate>TEST</ds:X509Certificate>
            </ds:X509Data>
        </ds:KeyInfo>
        </md:KeyDescriptor>
        <md:NameIDFormat>urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress</md:NameIDFormat>
        <md:SingleSignOnService Binding='urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST' Location='https://TEST/sso/saml'/>
        <md:SingleSignOnService Binding='urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect' Location='https://TEST/sso/saml'/>
    </md:IDPSSODescriptor>
    </md:EntityDescriptor>
    """
    SAMLConfiguration.objects.create(
        tenant_id=str(tenant_id),
        email_domain=domain,
        metadata_xml=metadata_xml,
    )

    return {
        "email": f"user@{domain}",
        "domain": domain,
        "tenant_id": tenant_id,
    }


@pytest.fixture
def saml_sociallogin(users_fixture):
    user = users_fixture[0]
    user.email = "samlsso@acme.com"
    extra_data = {
        "firstName": ["Test"],
        "lastName": ["User"],
        "organization": ["Prowler"],
        "userType": ["member"],
    }

    account = MagicMock()
    account.provider = "saml"
    account.extra_data = extra_data

    sociallogin = MagicMock(spec=SocialLogin)
    sociallogin.account = account
    sociallogin.user = user

    return sociallogin


def get_authorization_header(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


def pytest_collection_modifyitems(items):
    """Ensure test_rbac.py is executed first."""
    items.sort(key=lambda item: 0 if "test_rbac.py" in item.nodeid else 1)


def pytest_configure(config):
    # Apply the mock before the test session starts. This is necessary to avoid admin error when running the
    # 0004_rbac_missing_admin_roles migration
    patch("api.db_router.MainRouter.admin_db", new="default").start()


def pytest_unconfigure(config):
    # Stop all patches after the test session ends. This is necessary to avoid admin error when running the
    # 0004_rbac_missing_admin_roles migration
    patch.stopall()
