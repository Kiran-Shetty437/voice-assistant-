import smtplib
from email.mime.text import MIMEText
import sys

def test_email():
    SENDER_EMAIL = "uniplace.portal@gmail.com"
    APP_PASSWORD = "felcbounarbyoqx"
    TO_EMAIL = "uniplace.portal@gmail.com" # Sending to yourself to test

    print(f"Attempting to send test email to {TO_EMAIL}...")
    try:
        msg = MIMEText("This is a test email to verify credentials are working.", "plain")
        msg["Subject"] = "Test Email from CareerConnect"
        msg["From"] = f"CareerConnect <{SENDER_EMAIL}>"
        msg["To"] = TO_EMAIL

        print("Connecting to smtp.gmail.com...")
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.set_debuglevel(1) # This will print out the connection details
        server.starttls()
        
        print("Logging in...")
        server.login(SENDER_EMAIL, APP_PASSWORD)
        
        print("Sending message...")
        server.send_message(msg)
        server.quit()
        print("✅ Email sent successfully!")
        return True
    except smtplib.SMTPAuthenticationError:
        print("❌ Authentication failed: Please check if the App Password is correct.")
        return False
    except Exception as e:
        print(f"❌ Failed with error: {e}")
        return False

if __name__ == '__main__':
    test_email()
