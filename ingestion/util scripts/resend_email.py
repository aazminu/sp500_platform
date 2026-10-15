#!/usr/bin/env python3
import os
import resend
from datetime import date, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import json

load_dotenv(override=True)

DATABASE_URL = os.getenv("DATABASE_URL")
RESEND_API_KEY = os.getenv("RESEND_KEY")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")

if not RESEND_API_KEY:
    raise ValueError("RESEND_API_KEY environment variable is not set")

# Set up Resend API key
resend.api_key = RESEND_API_KEY

# Handle postgres:// to postgresql:// conversion
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

engine = create_engine(DATABASE_URL)

def send_test_email():
    """
    Send a simple test email to verify the email system is working.
    This will send even if weekly_stats table is empty or returns null.
    """
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    
    print(f"Sending test email for week: {week_start} to {week_end}")
    
    # Try to get stats, but don't fail if table is empty
    portfolio_return = 0.0
    top_5_changes = []
    scripts_executed = {}
    
    try:
        with engine.connect() as conn:
            # Try to get weekly stats
            stats = conn.execute(text("""
                SELECT portfolio_return_pct, top_5_notional_changes, scripts_executed 
                FROM weekly_stats 
                WHERE week_start_date = :week_start
                ORDER BY created_at DESC
                LIMIT 1
            """), {"week_start": week_start}).fetchone()
            
            if stats:
                portfolio_return = stats[0] if stats[0] else 0.0
                top_5_changes = json.loads(stats[1]) if stats[1] else []
                scripts_executed = json.loads(stats[2]) if stats[2] else {}
                print("Found existing weekly stats")
            else:
                print("No weekly stats found - sending basic email")
                
    except Exception as e:
        print(f"Database error (continuing anyway): {e}")
    
    # Create email content
    email_html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            .header {{ background-color: #f8f9fa; padding: 20px; border-radius: 8px; }}
            .section {{ margin: 20px 0; }}
            table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #f2f2f2; }}
            .success {{ color: green; }}
            .failure {{ color: red; }}
            .return-positive {{ color: green; }}
            .return-negative {{ color: red; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>📊 S&P 500 Platform Test Email</h1>
            <p><strong>Week:</strong> {week_start} to {week_end}</p>
            <p><strong>Sent:</strong> {date.today().isoformat()}</p>
        </div>
        
        <div class="section">
            <h2>💰 Portfolio Performance</h2>
            <p><strong>Weekly Return:</strong> 
                <span class="{'return-positive' if portfolio_return >= 0 else 'return-negative'}">
                    {portfolio_return:.2f}%
                </span>
            </p>
        </div>
    """
    
    if top_5_changes:
        email_html += """
            <div class="section">
                <h2>📈 Top 5 Position Changes</h2>
                <table>
                    <tr>
                        <th>Symbol</th>
                        <th>Market Value</th>
                        <th>P&L</th>
                        <th>Return %</th>
                    </tr>
        """
        
        for change in top_5_changes:
            return_class = "return-positive" if change['return_pct'] >= 0 else "return-negative"
            email_html += f"""
                <tr>
                    <td><strong>{change['symbol']}</strong></td>
                    <td>${change['market_value']:,.2f}</td>
                    <td class="{return_class}">${change['unrealized_pl']:,.2f}</td>
                    <td class="{return_class}">{change['return_pct']:.2f}%</td>
                </tr>
            """
        
        email_html += "</table></div>"
    else:
        email_html += """
            <div class="section">
                <h2>📈 Position Data</h2>
                <p>No position data available for this week.</p>
            </div>
        """
    
    # Add script execution status
    email_html += """
        <div class="section">
            <h2>🔧 Script Execution Status</h2>
            <ul>
    """
    
    if scripts_executed:
        for script, data in scripts_executed.items():
            status_class = "success" if data['success'] else "failure"
            status_icon = "✅" if data['success'] else "❌"
            email_html += f"""
                <li class="{status_class}">
                    <strong>{script}:</strong> {status_icon} {'Success' if data['success'] else 'Failed'}
            """
            if not data['success'] and data['error']:
                email_html += f" - {data['error']}"
            email_html += "</li>"
    else:
        email_html += "<li>No script execution data available.</li>"
    
    email_html += """
            </ul>
        </div>
        
        <div class="section">
            <p><em>This is a test email from S&P 500 Platform</em></p>
        </div>
    </body>
    </html>
    """
    
    # Send via Resend SDK
    try:
        params = {
            "from": os.getenv("REPORT_FROM_EMAIL", "S&P 500 Platform <noreply@sp500platform.local>"),
            "to": [os.getenv("REPORT_TO_EMAIL", "alerts@sp500platform.local")],
            "subject": f"📊 S&P 500 Platform Test Email - {date.today().isoformat()}",
            "html": email_html
        }
        
        email = resend.Emails.send(params)
        print("✅ Test email sent successfully")
        print(f"Email ID: {email.get('id', 'N/A')}")
        
    except Exception as e:
        print(f"❌ Error sending email: {str(e)}")

if __name__ == "__main__":
    send_test_email()
