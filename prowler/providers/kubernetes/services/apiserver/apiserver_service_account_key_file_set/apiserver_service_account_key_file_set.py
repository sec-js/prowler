from prowler.lib.check.models import Check, Check_Report_Kubernetes
from prowler.providers.kubernetes.services.apiserver.apiserver_client import (
    apiserver_client,
)


class apiserver_service_account_key_file_set(Check):
    def execute(self) -> Check_Report_Kubernetes:
        findings = []
        for pod in apiserver_client.apiserver_pods:
            report = Check_Report_Kubernetes(metadata=self.metadata(), resource=pod)
            report.status = "PASS"
            report.status_extended = (
                f"Service account key file is set appropriately in pod {pod.name}."
            )

            for container in pod.containers.values():
                # Check if "--service-account-key-file" is set
                if "--service-account-key-file" not in str(container.command):
                    report.status = "FAIL"
                    report.status_extended = (
                        f"Service account key file is not set in pod {pod.name}."
                    )
                    break

            findings.append(report)
        return findings
