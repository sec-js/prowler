from prowler.lib.check.models import Check, Check_Report_Azure
from prowler.providers.azure.services.app.app_client import app_client


class app_http_logs_enabled(Check):
    def execute(self) -> Check_Report_Azure:
        findings = []

        for subscription_name, apps in app_client.apps.items():
            for app in apps.values():
                if "functionapp" not in app.kind:
                    report = Check_Report_Azure(metadata=self.metadata(), resource=app)
                    report.subscription = subscription_name
                    report.status = "FAIL"
                    if not app.monitor_diagnostic_settings:
                        report.status_extended = f"App {app.name} does not have a diagnostic setting in subscription {subscription_name}."
                    else:
                        for diagnostic_setting in app.monitor_diagnostic_settings:
                            report.status_extended = f"App {app.name} does not have HTTP Logs enabled in diagnostic setting {diagnostic_setting.name} in subscription {subscription_name}"
                            for log in diagnostic_setting.logs:
                                if log.category == "AppServiceHTTPLogs" and log.enabled:
                                    report.status = "PASS"
                                    report.status_extended = f"App {app.name} has HTTP Logs enabled in diagnostic setting {diagnostic_setting.name} in subscription {subscription_name}"
                                    break
                    findings.append(report)

        return findings
