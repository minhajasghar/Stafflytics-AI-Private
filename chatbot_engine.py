import database
import re
from datetime import datetime

class StafflyticsIntelligenceAgent:
    def __init__(self):
        self.name = "Stafflytics Intelligence Agent"
        
    def process_query(self, query):
        query = query.lower().strip()
        
        # --- REASONING ENGINE: Intent Analysis ---
        if any(w in query for w in ["performance", "ranking", "how is", "efficiency"]):
            return self.reason_about_performance(query)
            
        if any(w in query for w in ["salary", "pay", "rate", "monthly", "hourly"]):
            return self.reason_about_compensation(query)

        if any(w in query for w in ["who", "active", "where", "shift", "roster"]):
            return self.reason_about_deployment(query)

        if any(w in query for w in ["summary", "insight", "today", "report"]):
            return self.get_executive_insight()

        return ("I'm analyzing your business data for patterns and well-being. Ask me about:\n"
                "- 'Analyze staff efficiency and engagement'\n"
                "- 'Who has been working too long without a break?'\n"
                "- 'Show today's shift distribution'")

    def reason_about_performance(self, query):
        """Chain-of-Thought Performance Reasoning"""
        metrics = database.get_detailed_performance_metrics()
        if not metrics: return "I don't have enough data yet to perform a deep analysis."

        # Analysis Step 1: Identify Top Performer
        best = sorted(metrics, key=lambda x: (x['days'] - x['late'] * 2), reverse=True)[0]
        
        # Analysis Step 2: Role-based context
        role_context = {
            "Chef": "crucial for kitchen consistency",
            "Manager": "vital for floor operations",
            "Waitstaff": "key for customer satisfaction"
        }
        ctx = role_context.get(best['role'], "performing well in their role")

        # synthesis
        resp = f"🧠 **Performance Analysis:**\n"
        resp += f"Based on recent data, **{best['name']}** is your standout performer. "
        resp += f"As a {best['role']}, they are {ctx}. "
        resp += f"They have worked {best['days']} days with only {best['late']} late arrivals.\n\n"
        
        # Deep Reasoning: Zone Efficiency
        resp += "🔍 **Operational Insight:**\n"
        resp += f"- Primary focus: **{best['zone']}**. "
        if best['zone'] == "Kitchen" and best['role'] == "Chef":
            resp += "This shows high adherence to their primary duty station."
        elif best['role'] == "Waitstaff" and best['zone'] == "Dining Area":
            resp += "Excellent! High presence in customer zones ensures better service."
        
        return resp

    def reason_about_compensation(self, query):
        """Administrative Compensation Info"""
        metrics = database.get_detailed_performance_metrics()
        
        resp = f"📋 **Administrative Compensation View:**\n"
        resp += "Here is the current salary configuration for the team:\n\n"
        for m in metrics:
            # Note: rate in detailed_performance_metrics should be updated if needed, but for now it's there
            resp += f"- **{m['name']}**: {m.get('rate', 'N/A')} (per administrative settings)\n"
        
        resp += "\n*Note: This view is for payroll administration only. Staff value is calculated through engagement and efficiency.*"
        return resp

    def reason_about_deployment(self, query):
        """Pakistani Restaurant Deployment Reasoning"""
        roster = database.get_todays_shift_roster()
        if not roster: return "The shift roster is currently empty."
        
        morning = [r for r in roster if r['shift'] == 'Morning']
        evening = [r for r in roster if r['shift'] == 'Evening']
        
        resp = "🏠 **Restaurant Deployment (Pakistani Context):**\n"
        if morning:
            resp += f"\n**Lunch Shift ({morning[0]['time']}):**\n"
            for m in morning: resp += f"- {m['name']} ({m['role']})\n"
            
        if evening:
            resp += f"\n**Dinner Shift (approx 6:00 PM):**\n"
            for e in evening: resp += f"- {e['name']} ({e['role']})\n"
            
        resp += "\n📊 **Coverage Reasoning:**\n"
        if len(morning) < len(evening):
            resp += "The dinner shift is more heavily staffed, which is ideal for peak Pakistani dining hours."
        else:
            resp += "Coverage is balanced across shifts."
            
        return resp

    def get_executive_insight(self):
        stats = database.get_comprehensive_summary()
        msg = f"📈 **Executive Dashboard Summary ({datetime.now().strftime('%d %b')}):**\n"
        msg += f"- Ops: {stats['staff_present']} Staff ({stats['late_count']} late)\n"
        msg += f"- Productivity: {stats['avg_efficiency']}% Avg Team Efficiency\n"
        msg += f"- Traffic: {stats['customers']} visitors, {stats['avg_stay']} min avg/stay\n"
        
        # Reasoning
        if stats['customers'] > 10 and stats['staff_present'] < 3:
            msg += "\n⚠️ **Bottleneck Alert:** High customer volume vs low staff count. Service quality may drop."
            
        return msg

chatbot = StafflyticsIntelligenceAgent()
