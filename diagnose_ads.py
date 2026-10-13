"""
Diagnostic script to check Google Ads account type and permissions.
"""
import os
from dotenv import load_dotenv

load_dotenv()

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

credentials = {
    "developer_token": os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN"),
    "client_id": os.getenv("GOOGLE_ADS_CLIENT_ID"),
    "client_secret": os.getenv("GOOGLE_ADS_CLIENT_SECRET"),
    "refresh_token": os.getenv("GOOGLE_ADS_REFRESH_TOKEN"),
    "use_proto_plus": True
}
customer_id = os.getenv("GOOGLE_ADS_TEST_ACCOUNT_ID", "").replace("-", "")

print(f"Checking account: {customer_id}")
print(f"Developer token: {credentials['developer_token'][:8]}...")

try:
    client = GoogleAdsClient.load_from_dict(credentials)
    ga_service = client.get_service("GoogleAdsService")

    query = """
        SELECT
            customer.id,
            customer.descriptive_name,
            customer.test_account,
            customer.manager,
            customer.status,
            customer.currency_code
        FROM customer
        LIMIT 1
    """
    response = ga_service.search(customer_id=customer_id, query=query)
    for row in response:
        c = row.customer
        print("\n=== Account Info ===")
        print(f"  ID:          {c.id}")
        print(f"  Name:        {c.descriptive_name}")
        print(f"  Is Test?:    {c.test_account}")
        print(f"  Is Manager?: {c.manager}")
        print(f"  Status:      {c.status.name}")
        print(f"  Currency:    {c.currency_code}")
        print("==================")

        if not c.test_account:
            print("\n⚠️  WARNING: This is a REAL (non-test) account!")
            print("   A pending developer token can ONLY operate on TEST accounts.")
            print("   You need to link a test account, not a real one.")
        else:
            print("\n✅ This is a test account - developer token should work.")

except GoogleAdsException as ex:
    print(f"\n❌ Google Ads API Error:")
    for error in ex.failure.errors:
        print(f"   {error.message}")
        if error.location:
            for el in error.location.field_path_elements:
                print(f"     → field: {el.field_name}")
except Exception as e:
    print(f"\n❌ Error: {e}")
