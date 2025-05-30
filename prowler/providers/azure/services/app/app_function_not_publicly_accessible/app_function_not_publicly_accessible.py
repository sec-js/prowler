from prowler.lib.check.models import Check, Check_Report_Azure
from prowler.providers.azure.services.app.app_client import app_client


class app_function_not_publicly_accessible(Check):
    def execute(self):
        findings = []

        for (
            subscription_name,
            functions,
        ) in app_client.functions.items():
            for function in functions.values():
                report = Check_Report_Azure(metadata=self.metadata(), resource=function)
                report.subscription = subscription_name
                report.status = "FAIL"
                report.status_extended = (
                    f"Function {function.name} is publicly accessible."
                )

                if not function.public_access:
                    report.status = "PASS"
                    report.status_extended = (
                        f"Function {function.name} is not publicly accessible."
                    )

                findings.append(report)

        return findings
