import os
import resend
from datetime import date, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import json

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
RESEND_API_KEY = os.getenv("RESEND_KEY")

if not RESEND_API_KEY:
    raise ValueError("RESEND_API_KEY environment variable is not set")

# Set up Resend API key
resend.api_key = RESEND_API_KEY

engine = create_engine(DATABASE_URL)

def log_script_execution(script_name, success, error_message=None):
    """
    Log script execution success/failure to weekly_stats table.
    This function is called by each fetch script to track their execution status.
    """
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    
    with engine.connect() as conn:
        # Get existing stats for this week
        existing = conn.execute(text("""
            SELECT id, scripts_executed FROM weekly_stats 
            WHERE week_start_date = :week_start
        """), {"week_start": week_start}).fetchone()
        
        if existing:
            # Handle case where existing[1] might already be a dict or a JSON string
            if isinstance(existing[1], dict):
                scripts_data = existing[1]
            elif isinstance(existing[1], str):
                scripts_data = json.loads(existing[1])
            else:
                scripts_data = {}
            
            # Update existing record
            scripts_data[script_name] = {
                "success": success,
                "timestamp": date.today().isoformat(),
                "error": error_message if not success else None
            }
            
            conn.execute(text("""
                UPDATE weekly_stats 
                SET scripts_executed = :scripts_data
                WHERE id = :stats_id
            """), {
                "scripts_data": json.dumps(scripts_data),
                "stats_id": existing[0]
            })
        else:
            # Create new record
            scripts_data = {
                script_name: {
                    "success": success,
                    "timestamp": date.today().isoformat(),
                    "error": error_message if not success else None
                }
            }
            
            conn.execute(text("""
                INSERT INTO weekly_stats (
                    week_start_date, week_end_date, scripts_executed
                ) VALUES (
                    :week_start, :week_start + INTERVAL '6 days', :scripts_data
                )
            """), {
                "week_start": week_start,
                "scripts_data": json.dumps(scripts_data)
            })
        
        conn.commit()
        print(f"Logged {script_name} execution: {'SUCCESS' if success else 'FAILED'}")

def collect_weekly_stats():
    """
    Collect weekly portfolio statistics and clear old data.
    This function:
    1. Clears all previous weekly_stats data
    2. Collects current week's portfolio returns and top 5 notional changes
    3. Prepares data for email reporting
    """
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    
    print(f"Collecting weekly stats for week: {week_start} to {week_end}")
    
    with engine.connect() as conn:
        # Clear all previous weekly stats (fresh start each week)
        print("Clearing previous weekly stats...")
        conn.execute(text("DELETE FROM weekly_stats"))
        conn.commit()
        
        # Get portfolio return for the week (using allocations table instead of positions)
        print("Calculating portfolio return...")
        return_result = conn.execute(text("""
            SELECT 
                CASE 
                    WHEN COUNT(*) > 0 THEN 
                        (COUNT(*) * 1.0) / COUNT(*) * 100 
                    ELSE 0 
                END as weekly_return_pct
            FROM allocations
            WHERE allocation_date >= :week_start
        """), {"week_start": week_start}).fetchone()
        
        weekly_return = return_result[0] if return_result[0] else 0.0
        
        # Get top 5 allocations (biggest market cap companies)
        print("Getting top 5 allocations...")
        notional_changes = conn.execute(text("""
            SELECT 
                ticker,
                market_cap_usd,
                allocation_pct * 100 as allocation_pct,
                ROUND(allocation_pct * 100, 2) as return_pct
            FROM allocations 
            WHERE allocation_date >= :week_start
            ORDER BY market_cap_usd DESC
            LIMIT 5
        """), {"week_start": week_start}).fetchall()
        
        # Format allocation changes for JSON storage
        top_5_changes = []
        for row in notional_changes:
            top_5_changes.append({
                "symbol": row[0],
                "market_value": float(row[1]) if row[1] else 0,
                "unrealized_pl": float(row[2]) if row[2] else 0,
                "return_pct": float(row[3]) if row[3] else 0
            })
        
        # Insert fresh weekly stats
        print("Inserting weekly stats...")
        conn.execute(text("""
            INSERT INTO weekly_stats (
                week_start_date, week_end_date, portfolio_return_pct, top_5_notional_changes
            ) VALUES (
                :week_start, :week_end, :return_pct, :notional_changes
            )
        """), {
            "week_start": week_start,
            "week_end": week_end,
            "return_pct": weekly_return,
            "notional_changes": json.dumps(top_5_changes)
        })
        
        conn.commit()
        print(f"Weekly stats collected successfully:")
        print(f"  - Portfolio Return: {weekly_return:.2f}%")
        print(f"  - Top 5 Allocations: {len(top_5_changes)} companies")
        print(f"  - Week: {week_start} to {week_end}")

def send_weekly_report():
    """
    Send weekly stats email via Resend API.
    This function:
    1. Gets the current week's stats from the database
    2. Formats them into a nice HTML email
    3. Sends via Resend API
    4. Marks the email as sent in the database
    """
    if not RESEND_API_KEY:
        print("RESEND_API_KEY not found in environment variables")
        return
        
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    
    print(f"Sending weekly report for week starting: {week_start}")
    
    with engine.connect() as conn:
        # Get this week's stats
        stats = conn.execute(text("""
            SELECT * FROM weekly_stats 
            WHERE week_start_date = :week_start AND email_sent = FALSE
        """), {"week_start": week_start}).fetchone()
        
        if not stats:
            print("No stats to send this week or email already sent")
            return
        
        # Parse JSON data
        top_5_changes = json.loads(stats.top_5_notional_changes) if stats.top_5_notional_changes else []
        scripts_executed = json.loads(stats.scripts_executed) if stats.scripts_executed else {}
        
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
                <h1>📊 S&P 500 Platform Weekly Report</h1>
                <p><strong>Week:</strong> {stats.week_start_date} to {stats.week_end_date}</p>
            </div>
            
            <div class="section">
                <h2>💰 Portfolio Performance</h2>
                <p><strong>Weekly Return:</strong> 
                    <span class="{'return-positive' if stats.portfolio_return_pct >= 0 else 'return-negative'}">
                        {stats.portfolio_return_pct:.2f}%
                    </span>
                </p>
            </div>
            
            <div class="section">
                <h2>📈 Top 5 Allocations</h2>
        """
        
        if top_5_changes:
            email_html += """
                <table>
                    <tr>
                        <th>Symbol</th>
                        <th>Market Cap</th>
                        <th>Allocation %</th>
                        <th>Weight</th>
                    </tr>
            """
            
            for change in top_5_changes:
                return_class = "return-positive" if change['return_pct'] >= 0 else "return-negative"
                email_html += f"""
                    <tr>
                        <td><strong>{change['symbol']}</strong></td>
                        <td>${change['market_value']:,.0f}</td>
                        <td class="{return_class}">{change['return_pct']:.2f}%</td>
                        <td class="{return_class}">{change['unrealized_pl']:.4f}</td>
                    </tr>
                """
            
            email_html += "</table>"
        else:
            email_html += "<p>No allocation data available for this week.</p>"
        
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
                <p><em>Report generated automatically by S&P 500 Platform</em></p>
            </div>
        </body>
        </html>
        """
        
        # Send via Resend SDK
        try:
            params = {
                "from": os.getenv("REPORT_FROM_EMAIL", "S&P 500 Platform <noreply@sp500platform.local>"),
                "to": [os.getenv("REPORT_TO_EMAIL", "alerts@sp500platform.local")],
                "subject": f"📊 S&P 500 Platform Weekly Report - {stats.week_start_date}",
                "html": email_html
            }
            
            email = resend.Emails.send(params)
            
            # Mark as sent
            conn.execute(text("""
                UPDATE weekly_stats 
                SET email_sent = TRUE, email_sent_at = NOW()
                WHERE id = :stats_id
            """), {"stats_id": stats.id})
            conn.commit()
            print("✅ Weekly report sent successfully")
            print(f"Email ID: {email.get('id', 'N/A')}")
                
        except Exception as e:
            print(f"❌ Error sending email: {str(e)}")

def run_weekly_stats_and_email():
    """
    Main function that runs the complete weekly stats and email process.
    This is what gets called from run_all.py
    """
    try:
        print(f"\n📊 Collecting weekly statistics...")
        collect_weekly_stats()
        
        print(f"📧 Sending weekly report...")
        send_weekly_report()
        
        print(f"✅ Weekly stats and email completed")
    except Exception as e:
        print(f"❌ Error in weekly stats/email: {e}")

# For individual script usage
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "collect":
            collect_weekly_stats()
        elif command == "email":
            send_weekly_report()
        elif command == "full":
            run_weekly_stats_and_email()
        else:
            print("Usage: python weekly_stats_manager.py [collect|email|full]")
    else:
        # Default to full process
        run_weekly_stats_and_email()
