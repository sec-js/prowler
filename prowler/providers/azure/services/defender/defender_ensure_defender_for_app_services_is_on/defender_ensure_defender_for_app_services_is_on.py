from prowler.lib.check.models import Check, Check_Report_Azure
from prowler.providers.azure.services.defender.defender_client import defender_client


class defender_ensure_defender_for_app_services_is_on(Check):
    def execute(self) -> Check_Report_Azure:
        findings = []
        for subscription, pricings in defender_client.pricings.items():
            if "AppServices" in pricings:
                report = Check_Report_Azure(
                    metadata=self.metadata(), resource=pricings["AppServices"]
                )
                report.subscription = subscription
                report.resource_name = "Defender plan App Services"
                report.status = "PASS"
                report.status_extended = f"Defender plan Defender for App Services from subscription {subscription} is set to ON (pricing tier standard)."
                if pricings["AppServices"].pricing_tier != "Standard":
                    report.status = "FAIL"
                    report.status_extended = f"Defender plan Defender for App Services from subscription {subscription} is set to OFF (pricing tier not standard)."

                findings.append(report)
        return findings
