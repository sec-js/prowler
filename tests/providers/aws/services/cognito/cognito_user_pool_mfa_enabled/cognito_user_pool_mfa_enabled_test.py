from datetime import datetime
from unittest import mock

from prowler.providers.aws.services.cognito.cognito_service import UserPool
from tests.providers.aws.utils import AWS_ACCOUNT_NUMBER, AWS_REGION_US_EAST_1


class Test_cognito_user_pool_mfa_enabled:
    def test_cognito_no_user_pools(self):
        cognito_client = mock.MagicMock
        cognito_client.user_pools = {}
        with (
            mock.patch(
                "prowler.providers.aws.services.cognito.cognito_service.CognitoIDP",
                new=cognito_client,
            ),
            mock.patch(
                "prowler.providers.aws.services.cognito.cognito_idp_client.cognito_idp_client",
                new=cognito_client,
            ),
        ):
            from prowler.providers.aws.services.cognito.cognito_user_pool_mfa_enabled.cognito_user_pool_mfa_enabled import (
                cognito_user_pool_mfa_enabled,
            )

            check = cognito_user_pool_mfa_enabled()
            result = check.execute()

            assert len(result) == 0

    def test_cognito_user_pools_mfa_config_none(self):
        cognito_client = mock.MagicMock
        user_pool_arn = f"arn:aws:cognito-idp:{AWS_REGION_US_EAST_1}:{AWS_ACCOUNT_NUMBER}:userpool/eu-west-1_123456789"
        user_pool_id = "eu-west-1_123456789"
        user_pool_name = "user_pool_name"
        cognito_client.user_pools = {
            user_pool_arn: UserPool(
                mfa_config=None,
                region=AWS_REGION_US_EAST_1,
                id=user_pool_id,
                arn=user_pool_arn,
                name=user_pool_name,
                last_modified=datetime.now(),
                creation_date=datetime.now(),
                status="ACTIVE",
            )
        }
        with (
            mock.patch(
                "prowler.providers.aws.services.cognito.cognito_service.CognitoIDP",
                new=cognito_client,
            ),
            mock.patch(
                "prowler.providers.aws.services.cognito.cognito_idp_client.cognito_idp_client",
                new=cognito_client,
            ),
        ):
            from prowler.providers.aws.services.cognito.cognito_user_pool_mfa_enabled.cognito_user_pool_mfa_enabled import (
                cognito_user_pool_mfa_enabled,
            )

            check = cognito_user_pool_mfa_enabled()
            result = check.execute()

            assert len(result) == 1
            assert result[0].status == "FAIL"
            assert result[0].status_extended == (
                f"User pool {user_pool_name} has MFA disabled."
            )

            assert result[0].resource_id == user_pool_id
            assert result[0].resource_arn == user_pool_arn

    def test_cognito_user_pools_mfa_config_disabled(self):
        cognito_client = mock.MagicMock
        user_pool_arn = f"arn:aws:cognito-idp:{AWS_REGION_US_EAST_1}:{AWS_ACCOUNT_NUMBER}:userpool/eu-west-1_123456789"
        user_pool_id = "eu-west-1_123456789"
        user_pool_name = "user_pool_name"
        cognito_client.user_pools = {
            user_pool_arn: UserPool(
                mfa_config={"status": "OFF"},
                region=AWS_REGION_US_EAST_1,
                id=user_pool_id,
                arn=user_pool_arn,
                name=user_pool_name,
                last_modified=datetime.now(),
                creation_date=datetime.now(),
                status="ACTIVE",
            )
        }
        with (
            mock.patch(
                "prowler.providers.aws.services.cognito.cognito_service.CognitoIDP",
                new=cognito_client,
            ),
            mock.patch(
                "prowler.providers.aws.services.cognito.cognito_idp_client.cognito_idp_client",
                new=cognito_client,
            ),
        ):
            from prowler.providers.aws.services.cognito.cognito_user_pool_mfa_enabled.cognito_user_pool_mfa_enabled import (
                cognito_user_pool_mfa_enabled,
            )

            check = cognito_user_pool_mfa_enabled()
            result = check.execute()

            assert len(result) == 1
            assert result[0].status == "FAIL"
            assert result[0].status_extended == (
                f"User pool {user_pool_name} has MFA disabled."
            )

            assert result[0].resource_id == user_pool_id
            assert result[0].resource_arn == user_pool_arn

    def test_cognito_user_pools_mfa_config_enabled(self):
        cognito_client = mock.MagicMock
        user_pool_arn = f"arn:aws:cognito-idp:{AWS_REGION_US_EAST_1}:{AWS_ACCOUNT_NUMBER}:userpool/eu-west-1_123456789"
        user_pool_id = "eu-west-1_123456789"
        user_pool_name = "user_pool_name"
        cognito_client.user_pools = {
            user_pool_arn: UserPool(
                mfa_config={"status": "ON"},
                region=AWS_REGION_US_EAST_1,
                id=user_pool_id,
                arn=user_pool_arn,
                name=user_pool_name,
                last_modified=datetime.now(),
                creation_date=datetime.now(),
                status="ACTIVE",
            )
        }
        with (
            mock.patch(
                "prowler.providers.aws.services.cognito.cognito_service.CognitoIDP",
                new=cognito_client,
            ),
            mock.patch(
                "prowler.providers.aws.services.cognito.cognito_idp_client.cognito_idp_client",
                new=cognito_client,
            ),
        ):
            from prowler.providers.aws.services.cognito.cognito_user_pool_mfa_enabled.cognito_user_pool_mfa_enabled import (
                cognito_user_pool_mfa_enabled,
            )

            check = cognito_user_pool_mfa_enabled()
            result = check.execute()

            assert len(result) == 1
            assert result[0].status == "PASS"
            assert result[0].status_extended == (
                f"User pool {user_pool_name} has MFA enabled."
            )

            assert result[0].resource_id == user_pool_id
            assert result[0].resource_arn == user_pool_arn
