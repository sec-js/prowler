from prowler.lib.check.models import Check, Check_Report_GCP
from prowler.providers.gcp.services.dataproc.dataproc_client import dataproc_client


class dataproc_encrypted_with_cmks_disabled(Check):
    def execute(self) -> Check_Report_GCP:
        findings = []
        for cluster in dataproc_client.clusters:
            report = Check_Report_GCP(
                metadata=self.metadata(),
                resource=cluster,
                location=dataproc_client.region,
            )
            report.status = "PASS"
            report.status_extended = f"Dataproc cluster {cluster.name} is encrypted with customer managed encryption keys."
            if cluster.encryption_config.get("gcePdKmsKeyName") is None:
                report.status = "FAIL"
                report.status_extended = f"Dataproc cluster {cluster.name} is not encrypted with customer managed encryption keys."
            findings.append(report)

        return findings
