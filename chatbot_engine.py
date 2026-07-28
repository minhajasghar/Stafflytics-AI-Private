import database
import json
import os
import re
import time
from datetime import datetime

try:
    import google.generativeai as genai
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
        GEMINI_AVAILABLE = True
    else:
        GEMINI_AVAILABLE = False
except ImportError:
    GEMINI_AVAILABLE = False

class StafflyticsIntelligenceAgent:
    def __init__(self):
        self.name = "Stafflytics Intelligence Agent"

    def _get_db_context(self):
        try:
            stats = database.get_comprehensive_summary()
            metrics = database.get_detailed_performance_metrics()
            roster = database.get_todays_shift_roster()
            cstats = database.get_monthly_customer_stats()
            wellbeing = database.get_wellbeing_data()

            context = f"""You are Stafflytics AI, a restaurant business intelligence assistant. Answer concisely using the data below.

Today: {datetime.now().strftime('%d %b %Y, %A')}

STAFF: {stats.get('staff_present', 0)} present, {stats.get('late_count', 0)} late, {stats.get('avg_efficiency', 0)}% avg efficiency.

CUSTOMERS: {cstats.get('monthly_total', 0)} monthly, {cstats.get('repeat_customers', 0)} returning. Avg stay {cstats.get('avg_visit', 0)} min.

WELLBEING: {len([w for w in wellbeing if w.get('needs_break')]) if wellbeing else 0} staff need breaks.

ROSTER ({len(roster)} staff): {', '.join([f"{r['name']} ({r['role']}, {r['shift']})" for r in roster[:5]])}

TOP PERFORMERS: {', '.join([f"{m['name']} ({m['role']}, {m['days']}d, {m['late']} late)" for m in sorted(metrics, key=lambda x: x['days'] - x['late']*2, reverse=True)[:3]]) if metrics else 'No data'}
"""
            return context
        except Exception as e:
            return f"Stafflytics AI active. Error fetching context: {e}"

    def _query_gemini(self, query):
        if not GEMINI_AVAILABLE or not GEMINI_API_KEY:
            return "⚠️ Gemini API not configured. Set a valid GEMINI_API_KEY in the .env file.\n\n*Get a free key at https://aistudio.google.com/apikey*"
        models_to_try = ['gemini-2.5-flash', 'gemini-2.0-flash']
        for model_name in models_to_try:
            for attempt in range(2):
                try:
                    model = genai.GenerativeModel(model_name)
                    context = self._get_db_context()
                    prompt = f"{context}\n\nAnswer this business query concisely using ONLY the data above. If the query is a greeting like 'hi' or 'thanks', just greet back briefly — do not include raw data. Never repeat the database context in your response.\n\nUser: {query}"
                    resp = model.generate_content(prompt, generation_config={'max_output_tokens': 500, 'temperature': 0.3})
                    return resp.text.strip() if resp and resp.text else None
                except Exception as e:
                    err = str(e)
                    print(f"[CHATBOT] Gemini API error ({model_name}): {err}")
                    delay_match = re.search(r'retry_delay\s*\{\s*seconds:\s*(\d+)', err)
                    if delay_match and attempt == 0:
                        delay = int(delay_match.group(1))
                        time.sleep(delay + 1)
                        continue
                    break
        return ("⚠️ Gemini API quota exceeded for all models. Try again later.\n\n"
                "• Daily free limit resets after 24h\n"
                "• Or create a new project at https://aistudio.google.com\n"
                "• Or set up billing for higher quota")

    def generate_shift_suggestions(self, hourly_data):
        if not hourly_data:
            return []
        try:
            context = self._get_db_context()
            data_str = "\n".join([
                f"Hour {h['hour']}: avg {h['staff']} staff, {h['activity']}% activity"
                for h in hourly_data
            ])
            prompt = f"""{context}

HOURLY STAFF ACTIVITY (last 7 days):
{data_str}

Analyze this restaurant staffing data and return a JSON array of shift optimization suggestions. Each suggestion must have:
- "time": hour range like "10:00 - 11:00"
- "type": "PEAK TRAFFIC", "Busy", "Low Activity", or "Understaffed"
- "advice": specific actionable recommendation (e.g. "Add 1 waiter", "Reduce to 1 chef", "Maintain current staff")
- "reason": brief data-driven explanation

Rules:
- Low activity + more than 2 staff → suggest reducing staff
- Activity > 75% → PEAK TRAFFIC, suggest adding staff
- Activity 50-75% → Busy, suggest maintaining
- If avg_staff is very low but activity is high → Understaffed, suggest urgent hiring
- Consider Pakistani restaurant context (dinner rush 7-10 PM, lunch 12-3 PM)

Return ONLY the JSON array, no markdown or extra text. Example:
[{{"time":"12:00 - 13:00","type":"PEAK TRAFFIC","advice":"Add 1 more waiter for lunch rush","reason":"92% activity with only 2 staff"}}]"""
            if GEMINI_AVAILABLE and GEMINI_API_KEY:
                model = genai.GenerativeModel('gemini-2.5-flash')
                resp = model.generate_content(prompt, generation_config={'max_output_tokens': 800, 'temperature': 0.3})
                if resp and resp.text:
                    text = resp.text.strip()
                    if text.startswith('```json'): text = text[7:]
                    elif text.startswith('```'): text = text[3:]
                    if text.endswith('```'): text = text[:-3]
                    text = text.strip()
                    parsed = json.loads(text)
                    if isinstance(parsed, list):
                        return parsed
        except Exception as e:
            print(f"[CHATBOT] Shift suggestion error: {e}")
        return []

    def process_query(self, query):
        gemini_resp = self._query_gemini(query)
        if gemini_resp:
            return gemini_resp

        query = query.lower().strip()

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
                "- 'Show today's shift distribution'"
                "\n\n*Tip: Set GEMINI_API_KEY environment variable for AI-powered responses.*")

    def reason_about_performance(self, query):
        metrics = database.get_detailed_performance_metrics()
        if not metrics: return "I don't have enough data yet to perform a deep analysis."
        best = sorted(metrics, key=lambda x: (x['days'] - x['late'] * 2), reverse=True)[0]
        role_context = {"Chef": "crucial for kitchen consistency", "Manager": "vital for floor operations", "Waitstaff": "key for customer satisfaction"}
        ctx = role_context.get(best['role'], "performing well in their role")
        resp = f"Based on recent data, **{best['name']}** is your standout performer. As a {best['role']}, they are {ctx}. They have worked {best['days']} days with only {best['late']} late arrivals.\n\n"
        resp += f"Primary focus: **{best['zone']}**. "
        if best['zone'] == "Kitchen" and best['role'] == "Chef":
            resp += "This shows high adherence to their primary duty station."
        elif best['role'] == "Waitstaff" and best['zone'] == "Dining Area":
            resp += "Excellent! High presence in customer zones ensures better service."
        return resp

    def reason_about_compensation(self, query):
        metrics = database.get_detailed_performance_metrics()
        resp = "Here is the current salary configuration for the team:\n"
        for m in metrics:
            resp += f"- **{m['name']}**: {m.get('rate', 'N/A')} (per administrative settings)\n"
        resp += "\n*Note: This view is for payroll administration only.*"
        return resp

    def reason_about_deployment(self, query):
        roster = database.get_todays_shift_roster()
        if not roster: return "The shift roster is currently empty."
        morning = [r for r in roster if r['shift'] == 'Morning']
        evening = [r for r in roster if r['shift'] == 'Evening']
        resp = "**Restaurant Deployment:**\n"
        if morning:
            resp += f"\n**Lunch Shift ({morning[0]['time']}):**\n"
            for m in morning: resp += f"- {m['name']} ({m['role']})\n"
        if evening:
            resp += f"\n**Dinner Shift (approx 6:00 PM):**\n"
            for e in evening: resp += f"- {e['name']} ({e['role']})\n"
        resp += "\n**Coverage Reasoning:**\n"
        if len(morning) < len(evening):
            resp += "The dinner shift is more heavily staffed, which is ideal for peak Pakistani dining hours."
        else:
            resp += "Coverage is balanced across shifts."
        return resp

    def get_executive_insight(self):
        stats = database.get_comprehensive_summary()
        msg = f"**Executive Dashboard Summary ({datetime.now().strftime('%d %b')}):**\n"
        msg += f"- Ops: {stats['staff_present']} Staff ({stats['late_count']} late)\n"
        msg += f"- Productivity: {stats['avg_efficiency']}% Avg Team Efficiency\n"
        msg += f"- Traffic: {stats['customers']} visitors, {stats['avg_stay']} min avg/stay\n"
        if stats['customers'] > 10 and stats['staff_present'] < 3:
            msg += "\n⚠ **Bottleneck Alert:** High customer volume vs low staff count. Service quality may drop."
        return msg

chatbot = StafflyticsIntelligenceAgent()
