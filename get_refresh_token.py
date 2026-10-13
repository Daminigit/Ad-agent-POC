import os
from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

load_dotenv()

def main():
    CLIENT_ID = os.getenv("GOOGLE_ADS_CLIENT_ID")
    CLIENT_SECRET = os.getenv("GOOGLE_ADS_CLIENT_SECRET")

    if not CLIENT_ID or not CLIENT_SECRET:
        print("Error: GOOGLE_ADS_CLIENT_ID or GOOGLE_ADS_CLIENT_SECRET is missing from your .env file.")
        return

    client_config = {
        "installed": {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    
    # The required scope for Google Ads API
    scopes = ["https://www.googleapis.com/auth/adwords"]
    
    try:
        # Create the flow
        flow = InstalledAppFlow.from_client_config(client_config, scopes)
        
        # This will automatically open a browser window for you to log in
        print("Opening your browser to log into Google...")
        credentials = flow.run_local_server(port=0, prompt='consent')
        
        print("\n" + "="*50)
        print("SUCCESS! Here is your Refresh Token:")
        print("="*50)
        print(credentials.refresh_token)
        print("="*50 + "\n")
        print("Copy the token above and paste it into your .env file next to GOOGLE_ADS_REFRESH_TOKEN=")
        
    except Exception as e:
        print(f"\nError getting refresh token: {e}")

if __name__ == "__main__":
    main()
