import os
import time
import datetime
from typing import Dict, Any, Optional

try:
    from google.ads.googleads.client import GoogleAdsClient
    from google.ads.googleads.errors import GoogleAdsException
except ImportError:
    GoogleAdsClient = None
    GoogleAdsException = Exception

def publish_to_google_ads(
    project_id: str,
    creative_data: Dict[str, Any],
    copy_data: Dict[str, Any],
    final_url: str = "https://example.com/property"
) -> Dict[str, str]:
    """
    Publish the generated ad to a Google Ads test account.
    
    Creates a Search Campaign, Ad Group, and Responsive Search Ad.
    """
    developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")
    client_id = os.getenv("GOOGLE_ADS_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_ADS_CLIENT_SECRET")
    refresh_token = os.getenv("GOOGLE_ADS_REFRESH_TOKEN")
    customer_id = os.getenv("GOOGLE_ADS_TEST_ACCOUNT_ID")
    
    if not (developer_token and client_id and client_secret and refresh_token and customer_id):
        # Simulation Mode
        print("[Publisher] Simulation Mode: Missing Google Ads credentials.")
        return _simulate_publish(creative_data, copy_data)
        
    if not GoogleAdsClient:
        return {
            "status": "error",
            "message": "google-ads library is not installed."
        }
        
    # Real Publishing Mode
    try:
        credentials = {
            "developer_token": developer_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "use_proto_plus": True
        }
        client = GoogleAdsClient.load_from_dict(credentials)
        customer_id = customer_id.replace("-", "") # Ensure no dashes
        
        # 1. Create a Campaign Budget
        budget_resource_name = _create_campaign_budget(client, customer_id)
        
        # 2. Create a Search Campaign
        campaign_resource_name = _create_search_campaign(client, customer_id, budget_resource_name, project_id)
        
        # 3. Create an Ad Group
        ad_group_resource_name = _create_ad_group(client, customer_id, campaign_resource_name)
        
        # 4. Create Responsive Search Ad
        ad_preview_url = _create_responsive_search_ad(client, customer_id, ad_group_resource_name, copy_data, final_url)
        
        return {
            "status": "success",
            "message": "Successfully published Search Ad to Google Ads!",
            "preview_url": ad_preview_url
        }
        
    except GoogleAdsException as ex:
        err_messages = []
        for error in ex.failure.errors:
            field_paths = ".".join([elem.field_name for elem in error.location.field_path_elements])
            err_messages.append(f"API Error ({field_paths}): {error.message}")
        return {
            "status": "error",
            "message": f"Google Ads API Error: {', '.join(err_messages)}"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to publish: {e}"
        }

def _simulate_publish(creative_data: Dict[str, Any], copy_data: Dict[str, Any]) -> Dict[str, str]:
    """Simulates the API latency and returns a mock success."""
    print("[Publisher] Simulating Google Ads Campaign Creation...")
    time.sleep(1.5)
    print("[Publisher] Simulating Ad Group Creation...")
    time.sleep(1.0)
    print("[Publisher] Constructing Responsive Search Ad...")
    
    # Extract copy for logging
    google_copy = copy_data.get("google_search", {})
    headlines = google_copy.get("headlines", ["Property Ad"])
    descriptions = google_copy.get("descriptions", ["Check out this property."])
    
    print(f"[Publisher] Injecting Headlines: {headlines[:2]}...")
    print(f"[Publisher] Injecting Descriptions: {descriptions[:1]}...")
    time.sleep(1.0)
    
    return {
        "status": "success",
        "message": "Simulated publishing to Google Ads!",
        "preview_url": "https://ads.google.com/aw/diagnostic/adpreview?ocid=TEST_ACCOUNT_ID",
        "is_simulation": "true"
    }

def _create_campaign_budget(client, customer_id: str) -> str:
    budget_service = client.get_service("CampaignBudgetService")
    campaign_budget_operation = client.get_type("CampaignBudgetOperation")
    campaign_budget = campaign_budget_operation.create
    campaign_budget.name = f"Property Ad Budget #{int(time.time())}"
    campaign_budget.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD
    campaign_budget.amount_micros = 50000000  # $50
    # Must be non-shared so it works with automated bidding strategies
    campaign_budget.explicitly_shared = False
    
    response = budget_service.mutate_campaign_budgets(
        customer_id=customer_id, operations=[campaign_budget_operation]
    )
    return response.results[0].resource_name

def _create_search_campaign(client, customer_id: str, budget_resource_name: str, project_id: str) -> str:
    campaign_service = client.get_service("CampaignService")
    campaign_operation = client.get_type("CampaignOperation")
    campaign = campaign_operation.create
    campaign.name = f"Property Search Campaign - Project {project_id[:8]} #{int(time.time())}"
    campaign.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.SEARCH
    campaign.status = client.enums.CampaignStatusEnum.PAUSED
    
    # TargetSpend = "Maximize Clicks" — works on all account types including test accounts
    campaign.target_spend = client.get_type("TargetSpend")
    
    # Required field for recent Google Ads API versions
    campaign.contains_eu_political_advertising = client.enums.EuPoliticalAdvertisingStatusEnum.DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING
    campaign.campaign_budget = budget_resource_name
    
    campaign.network_settings.target_google_search = True
    campaign.network_settings.target_search_network = True
    campaign.network_settings.target_content_network = False
    campaign.network_settings.target_partner_search_network = False
    
    response = campaign_service.mutate_campaigns(
        customer_id=customer_id, operations=[campaign_operation]
    )
    return response.results[0].resource_name

def _create_ad_group(client, customer_id: str, campaign_resource_name: str) -> str:
    ad_group_service = client.get_service("AdGroupService")
    ad_group_operation = client.get_type("AdGroupOperation")
    ad_group = ad_group_operation.create
    ad_group.name = f"Property Ad Group #{int(time.time())}"
    ad_group.status = client.enums.AdGroupStatusEnum.ENABLED
    ad_group.campaign = campaign_resource_name
    ad_group.type_ = client.enums.AdGroupTypeEnum.SEARCH_STANDARD
    ad_group.cpc_bid_micros = 1000000 # $1
    
    response = ad_group_service.mutate_ad_groups(
        customer_id=customer_id, operations=[ad_group_operation]
    )
    return response.results[0].resource_name

def _create_responsive_search_ad(client, customer_id: str, ad_group_resource_name: str, copy_data: Dict[str, Any], final_url: str) -> str:
    ad_group_ad_service = client.get_service("AdGroupAdService")
    ad_group_ad_operation = client.get_type("AdGroupAdOperation")
    ad_group_ad = ad_group_ad_operation.create
    ad_group_ad.ad_group = ad_group_resource_name
    ad_group_ad.status = client.enums.AdGroupAdStatusEnum.PAUSED
    
    ad = ad_group_ad.ad
    ad.final_urls.append(final_url)
    
    google_copy = copy_data.get("google_search", {})
    headlines = google_copy.get("headlines", ["Amazing Property"])
    descriptions = google_copy.get("descriptions", ["Check out this amazing property today!"])
    
    for hl in headlines[:15]:
        text_asset = client.get_type("AdTextAsset")
        text_asset.text = hl
        ad.responsive_search_ad.headlines.append(text_asset)
        
    for desc in descriptions[:4]:
        text_asset = client.get_type("AdTextAsset")
        text_asset.text = desc
        ad.responsive_search_ad.descriptions.append(text_asset)
        
    ad.responsive_search_ad.path1 = "Property"
    ad.responsive_search_ad.path2 = "Details"
    
    response = ad_group_ad_service.mutate_ad_group_ads(
        customer_id=customer_id, operations=[ad_group_ad_operation]
    )
    
    return f"https://ads.google.com/aw/campaigns?ocid={customer_id}"
