from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import asyncio
import random
import time
import re
import requests
import json
from datetime import datetime

app = FastAPI(title="Gym Social Scraper", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Models ───────────────────────────────────────────────────────────────────

class GymInput(BaseModel):
    gym_name: str
    facebook_url: Optional[str] = None
    instagram_username: Optional[str] = None

class ScrapeRequest(BaseModel):
    gyms: List[GymInput]
    delay_seconds: float = 3.0  # delay between requests to avoid bans

class ProfileResult(BaseModel):
    gym_name: str
    facebook_url: Optional[str] = None
    fb_name: Optional[str] = None
    fb_followers: Optional[str] = None
    fb_likes: Optional[str] = None
    fb_phone: Optional[str] = None
    fb_email: Optional[str] = None
    fb_website: Optional[str] = None
    fb_address: Optional[str] = None
    fb_about: Optional[str] = None
    fb_error: Optional[str] = None
    instagram_username: Optional[str] = None
    ig_full_name: Optional[str] = None
    ig_bio: Optional[str] = None
    ig_followers: Optional[int] = None
    ig_following: Optional[int] = None
    ig_posts: Optional[int] = None
    ig_website: Optional[str] = None
    ig_is_verified: Optional[bool] = None
    ig_error: Optional[str] = None
    scraped_at: str = ""

# ─── Facebook Scraper ─────────────────────────────────────────────────────────

def scrape_facebook_page(url: str) -> dict:
    """
    Scrapes a public Facebook page using facebook-scraper library.
    Extracts profile/about info: name, followers, phone, address, website.
    """
    try:
        from facebook_scraper import get_profile
        
        # Extract page name/id from URL
        # Handles: facebook.com/pagename or facebook.com/pages/name/id
        match = re.search(r'facebook\.com/(?:pages/[^/]+/(\d+)|([^/?#]+))', url)
        if not match:
            return {"error": "Could not parse Facebook URL"}
        
        page_id = match.group(1) or match.group(2)
        # Remove trailing slashes or query params
        page_id = page_id.strip("/").split("?")[0]
        
        profile = get_profile(page_id)
        
        return {
            "name": profile.get("Name"),
            "followers": profile.get("Followers") or profile.get("People follow"),
            "likes": profile.get("Likes") or profile.get("People like"),
            "phone": profile.get("Phone"),
            "email": profile.get("Email"),
            "website": profile.get("Website"),
            "address": profile.get("Address") or profile.get("Location"),
            "about": profile.get("About") or profile.get("Description"),
        }
    except Exception as e:
        return {"error": str(e)}


# ─── Instagram Scraper ────────────────────────────────────────────────────────

def scrape_instagram_profile(username: str) -> dict:
    """
    Scrapes a public Instagram profile using the unofficial i.instagram.com API.
    No login required for public profiles.
    """
    try:
        username = username.lstrip("@").strip()
        
        headers = {
            "User-Agent": "Instagram 123.0.0.21.114 Android",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.8",
        }
        
        url = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}"
        
        resp = requests.get(url, headers=headers, timeout=15)
        
        if resp.status_code == 404:
            return {"error": "Profile not found"}
        if resp.status_code == 429:
            return {"error": "Rate limited by Instagram — wait before retrying"}
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}"}
        
        data = resp.json()
        user = data.get("data", {}).get("user", {})
        
        if not user:
            return {"error": "No user data returned"}
        
        return {
            "full_name": user.get("full_name"),
            "bio": user.get("biography"),
            "followers": user.get("edge_followed_by", {}).get("count"),
            "following": user.get("edge_follow", {}).get("count"),
            "posts": user.get("edge_owner_to_timeline_media", {}).get("count"),
            "website": user.get("external_url"),
            "is_verified": user.get("is_verified"),
        }
    except Exception as e:
        return {"error": str(e)}


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {
        "status": "running",
        "endpoints": {
            "POST /scrape": "Scrape a list of gyms (FB + IG)",
            "GET /scrape/facebook?url=...": "Scrape single Facebook page",
            "GET /scrape/instagram?username=...": "Scrape single Instagram profile",
            "GET /health": "Health check"
        }
    }

@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


@app.get("/scrape/facebook")
def scrape_single_facebook(url: str):
    result = scrape_facebook_page(url)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.get("/scrape/instagram")
def scrape_single_instagram(username: str):
    result = scrape_instagram_profile(username)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/scrape")
def scrape_gyms(request: ScrapeRequest):
    """
    Accepts a list of gyms with FB URLs and/or IG usernames.
    Returns enriched data for each. Adds delay between requests.
    Batch this — send 50 gyms at a time for best results.
    """
    results = []
    
    for i, gym in enumerate(request.gyms):
        result = ProfileResult(
            gym_name=gym.gym_name,
            scraped_at=datetime.utcnow().isoformat()
        )
        
        # Scrape Facebook
        if gym.facebook_url:
            result.facebook_url = gym.facebook_url
            fb_data = scrape_facebook_page(gym.facebook_url)
            if "error" in fb_data:
                result.fb_error = fb_data["error"]
            else:
                result.fb_name = fb_data.get("name")
                result.fb_followers = fb_data.get("followers")
                result.fb_likes = fb_data.get("likes")
                result.fb_phone = fb_data.get("phone")
                result.fb_email = fb_data.get("email")
                result.fb_website = fb_data.get("website")
                result.fb_address = fb_data.get("address")
                result.fb_about = fb_data.get("about")
        
        # Delay between requests
        if i > 0:
            jitter = random.uniform(0.5, 1.5)
            time.sleep(request.delay_seconds + jitter)
        
        # Scrape Instagram
        if gym.instagram_username:
            result.instagram_username = gym.instagram_username
            ig_data = scrape_instagram_profile(gym.instagram_username)
            if "error" in ig_data:
                result.ig_error = ig_data["error"]
            else:
                result.ig_full_name = ig_data.get("full_name")
                result.ig_bio = ig_data.get("bio")
                result.ig_followers = ig_data.get("followers")
                result.ig_following = ig_data.get("following")
                result.ig_posts = ig_data.get("posts")
                result.ig_website = ig_data.get("website")
                result.ig_is_verified = ig_data.get("is_verified")
        
        results.append(result.dict())
        
        # Extra delay between gyms
        if i < len(request.gyms) - 1:
            time.sleep(request.delay_seconds + random.uniform(0.5, 1.5))
    
    return {
        "total": len(results),
        "scraped_at": datetime.utcnow().isoformat(),
        "results": results
    }
