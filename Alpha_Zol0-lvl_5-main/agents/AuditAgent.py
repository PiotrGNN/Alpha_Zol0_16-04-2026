# AuditAgent – audytuje decyzje
class AuditAgent:
    def vote(self, audit_data):
        # Przykład: audit_data = {'last_decision': 'buy', 'success_rate': 0.6}
        if audit_data.get("success_rate", 0) < 0.5:
            return "wait"
        return audit_data.get("last_decision", "wait")
