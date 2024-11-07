#!/usr/bin/env python3
# inst.py

import instaloader
import os
import argparse
from datetime import datetime
import sys
import configparser
from pathlib import Path
from tqdm import tqdm
import time
import math
from typing import Optional, Set
import re
import requests
from urllib.parse import urlparse, unquote
import json
import glob
from bs4 import BeautifulSoup
import random

def clamp_delay(delay: float) -> float:
    """Ensure delay is between 1 and 3 seconds"""
    return max(1.0, min(3.0, delay))

class TikTokDownloader:
    def __init__(self, delay: float = 3.0, max_retries: int = 3):
        self.delay = clamp_delay(delay)
        if abs(delay - self.delay) > 0.01:
            print(f"⚠️  Delay adjusted to {self.delay}s (must be between 1-3 seconds)")
        self.max_retries = max_retries
        self.history_file = os.path.expanduser('~/.config/inst/tiktok_history.json')
        self.downloaded_ids = self._load_history()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/json,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'DNT': '1'
        }

    def _load_history(self) -> dict:
        """Load download history from file"""
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_history(self):
        """Save download history to file"""
        os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
        with open(self.history_file, 'w') as f:
            json.dump(self.downloaded_ids, f)

    def _is_already_downloaded(self, username: str, video_id: str) -> bool:
        """Check if a video has already been downloaded"""
        if username in self.downloaded_ids:
            return video_id in self.downloaded_ids[username]
        return False

    def _mark_as_downloaded(self, username: str, video_id: str):
        """Mark a video as downloaded in history"""
        if username not in self.downloaded_ids:
            self.downloaded_ids[username] = []
        if video_id not in self.downloaded_ids[username]:
            self.downloaded_ids[username].append(video_id)
            self._save_history()

    def _get_random_delay(self) -> float:
        """Get a random delay between current delay and 3 seconds"""
        max_additional_delay = min(3.0 - self.delay, 1.0)
        return self.delay + random.uniform(0, max_additional_delay)

    def _extract_video_id(self, url: str) -> str:
        """Extract video ID from TikTok URL"""
        url = unquote(url)  # Handle URL encoding
        if '/video/' in url:
            video_id = url.split('/video/')[1].split('?')[0].split('/')[0]
            return video_id
        raise ValueError("Invalid TikTok URL format")

    def _extract_username(self, url: str) -> str:
        """Extract username from TikTok URL"""
        url = unquote(url)
        if '/@' in url:
            username = url.split('/@')[1].split('/')[0]
            return username
        raise ValueError("Could not extract username from URL")

    def _get_video_info(self, url: str) -> dict:
        """Get video information using multiple methods"""
        try:
            video_id = self._extract_video_id(url)
            username = self._extract_username(url)
            
            # Try oembed endpoint first
            oembed_url = f"https://www.tiktok.com/oembed?url={url}"
            response = requests.get(oembed_url, headers=self.headers)
            
            if response.ok:
                data = response.json()
                return {
                    'video_id': video_id,
                    'username': username,
                    'title': data.get('title', 'No title'),
                    'author_name': data.get('author_name', username).replace('@', '')
                }
            
            # Fallback to basic info
            return {
                'video_id': video_id,
                'username': username,
                'title': 'No title available',
                'author_name': username
            }
            
        except Exception as e:
            raise Exception(f"Failed to get video info: {str(e)}")
        
    def download_single_video(self, url: str) -> bool:
        """Download a single TikTok video"""
        try:
            # Clean and validate URL
            url = url.split('?')[0]  # Remove query parameters
            
            video_info = self._get_video_info(url)
            username = video_info['username']
            video_id = video_info['video_id']

            download_path = os.path.join(os.getcwd(), "downloads", "tiktok", username)
            os.makedirs(download_path, exist_ok=True)

            print(f"📱 Downloading video from @{username}...")

            if self._is_already_downloaded(username, video_id):
                print(f"⏭️  Skipping video (already downloaded)")
                return True

            # Use desktop browser headers
            desktop_headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Range': 'bytes=0-',
                'Connection': 'keep-alive',
                'Referer': 'https://www.tiktok.com/',
                'Sec-Fetch-Dest': 'video',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-site',
                'Origin': 'https://www.tiktok.com',
                'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'Pragma': 'no-cache',
                'Cache-Control': 'no-cache',
            }

            # First, get the HTML page to extract the video URL
            session = requests.Session()
            response = session.get(url, headers=desktop_headers)
            response.raise_for_status()
            
            # Look for the video URL in the HTML
            video_pattern = r'"downloadAddr":"([^"]+)"'
            matches = re.findall(video_pattern, response.text)
            
            if not matches:
                # Try alternative pattern
                video_pattern = r'"playAddr":"([^"]+)"'
                matches = re.findall(video_pattern, response.text)
            
            if not matches:
                raise Exception("Could not find video URL in page source")
                
            video_url = matches[0].replace('\\u002F', '/').replace('\\/', '/')
            
            # Download the video
            timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            filename = f"{username}_{timestamp}_{video_id}.mp4"
            filepath = os.path.join(download_path, filename)

            print("⬇️  Downloading video...")
            response = session.get(video_url, headers=desktop_headers, stream=True)
            response.raise_for_status()

            file_size = int(response.headers.get('content-length', 0))
            block_size = 8192

            with tqdm(total=file_size, unit='iB', unit_scale=True) as pbar:
                with open(filepath, 'wb') as f:
                    for data in response.iter_content(block_size):
                        pbar.update(len(data))
                        f.write(data)

            # Verify the file was downloaded successfully
            if os.path.getsize(filepath) == 0:
                os.remove(filepath)
                raise Exception("Downloaded file is empty")

            # Save metadata
            meta_filename = os.path.splitext(filename)[0] + '.txt'
            meta_filepath = os.path.join(download_path, meta_filename)
            with open(meta_filepath, 'w', encoding='utf-8') as f:
                f.write(f"Video ID: {video_id}\n")
                f.write(f"Username: {username}\n")
                f.write(f"Title: {video_info.get('title', 'No title')}\n")
                f.write(f"Download Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Original URL: {url}\n")

            self._mark_as_downloaded(username, video_id)
            print(f"✅ Successfully downloaded video to {download_path}")
            return True

        except Exception as e:
            print(f"❌ Failed to download video: {str(e)}")
            if "403" in str(e):
                print("\nAccess Denied (403) Error. This usually means:")
                print("1. The video might be private")
                print("2. TikTok's protection system blocked the request")
                print("3. Try again in a few minutes")
            return False
        
    def _get_user_videos(self, username: str) -> list:
        """Get list of video URLs for a user"""
        try:
            user_url = f"https://www.tiktok.com/@{username}"
            response = requests.get(user_url, headers=self.headers)
            response.raise_for_status()
            
            # Extract video IDs from the page
            video_ids = re.findall(r'"videoId":"(\d+)"', response.text)
            
            return [f"https://www.tiktok.com/@{username}/video/{vid}" for vid in video_ids]
            
        except Exception as e:
            raise Exception(f"Failed to get user videos: {str(e)}")

    def download_user_videos(self, username: str, limit: Optional[int] = None):
        """Download all videos from a TikTok user"""
        try:
            print(f"📱 Fetching videos for @{username}...")
            
            # Get list of video URLs
            video_urls = self._get_user_videos(username)
            
            if limit:
                video_urls = video_urls[:limit]
                
            if not video_urls:
                print("❌ No videos found")
                return

            print(f"Found {len(video_urls)} videos")
            
            # Download each video
            success_count = 0
            for i, url in enumerate(video_urls, 1):
                print(f"\nProcessing video {i}/{len(video_urls)}")
                if self.download_single_video(url):
                    success_count += 1
                time.sleep(self._get_random_delay())

            print(f"\n✅ Successfully downloaded {success_count}/{len(video_urls)} videos")

        except Exception as e:
            print(f"❌ Failed to download user videos: {str(e)}")
            sys.exit(1)

class ReelsDownloader:
    def __init__(self, delay: float = 3.0, max_retries: int = 3):
        self.delay = clamp_delay(delay)
        if abs(delay - self.delay) > 0.01:  # If delay was adjusted
            print(f"⚠️  Delay adjusted to {self.delay}s (must be between 1-3 seconds)")
        self.max_retries = max_retries
        self.L = instaloader.Instaloader(
            download_videos=True,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=True,
            download_pictures=False
        )
        self.config_file = os.path.expanduser('~/.config/inst/config.ini')
        self.history_file = os.path.expanduser('~/.config/inst/download_history.json')
        self._load_config()
        self.downloaded_shortcuts = self._load_history()

    def _get_random_delay(self) -> float:
        """Get a random delay between current delay and 3 seconds"""
        max_additional_delay = min(3.0 - self.delay, 1.0)  # Ensure we don't exceed 3s
        return self.delay + random.uniform(0, max_additional_delay)

    def _load_config(self):
        """Load credentials from config file"""
        config = configparser.ConfigParser()
        
        if os.path.exists(self.config_file):
            config.read(self.config_file)
            if 'Credentials' in config:
                username = config['Credentials'].get('username')
                password = config['Credentials'].get('password')
                if username and password:
                    try:
                        self.L.login(username, password)
                        print("✅ Logged in successfully")
                    except Exception as e:
                        print(f"⚠️  Warning: Auto-login failed: {str(e)}")

    def _load_history(self) -> dict:
        """Load download history from file"""
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_history(self):
        """Save download history to file"""
        os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
        with open(self.history_file, 'w') as f:
            json.dump(self.downloaded_shortcuts, f)

    def _is_already_downloaded(self, username: str, shortcode: str) -> bool:
        """Check if a reel has already been downloaded"""
        if username in self.downloaded_shortcuts:
            if shortcode in self.downloaded_shortcuts[username]:
                return True
                
        download_path = os.path.join(os.getcwd(), "downloads", username)
        if os.path.exists(download_path):
            matching_files = glob.glob(os.path.join(download_path, f"*{shortcode}*"))
            if matching_files:
                if username not in self.downloaded_shortcuts:
                    self.downloaded_shortcuts[username] = []
                if shortcode not in self.downloaded_shortcuts[username]:
                    self.downloaded_shortcuts[username].append(shortcode)
                    self._save_history()
                return True
        
        return False

    def _mark_as_downloaded(self, username: str, shortcode: str):
        """Mark a reel as downloaded in history"""
        if username not in self.downloaded_shortcuts:
            self.downloaded_shortcuts[username] = []
        if shortcode not in self.downloaded_shortcuts[username]:
            self.downloaded_shortcuts[username].append(shortcode)
            self._save_history()

    def _retry_download(self, post, target_path: str) -> bool:
        """Retry download with fresh URL"""
        for attempt in range(self.max_retries):
            try:
                # Force refresh post data
                fresh_post = instaloader.Post.from_shortcode(self.L.context, post.shortcode)
                
                try:
                    post_data = self.L.context.get_json(f"https://www.instagram.com/p/{post.shortcode}/?__a=1")
                    video_url = post_data['graphql']['shortcode_media']['video_url']
                except Exception:
                    video_url = fresh_post.video_url
                
                if not video_url:
                    return False

                response = requests.get(video_url, stream=True)
                response.raise_for_status()
                
                filename = f"{post.owner_username}_{post.date_utc.strftime('%Y-%m-%d_%H-%M-%S')}_{post.shortcode}.mp4"
                filepath = os.path.join(target_path, filename)
                
                with open(filepath, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                
                meta_filename = os.path.splitext(filename)[0] + '.txt'
                meta_filepath = os.path.join(target_path, meta_filename)
                with open(meta_filepath, 'w', encoding='utf-8') as f:
                    f.write(f"Shortcode: {post.shortcode}\n")
                    f.write(f"Caption: {post.caption or 'No caption'}\n")
                    f.write(f"Posted on: {post.date_local}\n")
                    f.write(f"Likes: {post.likes}\n")
                    f.write(f"URL: https://www.instagram.com/p/{post.shortcode}/\n")
                
                self._mark_as_downloaded(post.owner_username, post.shortcode)
                return True
                
            except Exception as e:
                print(f"\n⚠️  Retry {attempt + 1}/{self.max_retries} failed: {str(e)}")
                time.sleep(self._get_random_delay())
                
        return False

    def _get_video_size_mb(self, post) -> float:
        """Get video size in megabytes"""
        try:
            response = self.L.context.get_json(f"https://www.instagram.com/p/{post.shortcode}/?__a=1")
            video_url = response['graphql']['shortcode_media']['video_url']
            size_bytes = int(self.L.context.head(video_url).headers.get('content-length', 0))
            return size_bytes / (1024 * 1024)
        except Exception:
            return 0

    def _get_video_duration(self, post) -> float:
        """Get video duration in seconds"""
        try:
            return float(post.video_duration)
        except Exception:
            return 0

    def _meets_criteria(self, post, min_size: Optional[float] = None, min_duration: Optional[float] = None) -> bool:
        """Check if post meets the size and duration criteria"""
        if min_size is not None:
            size_mb = self._get_video_size_mb(post)
            if size_mb < min_size:
                return False
                
        if min_duration is not None:
            duration_seconds = self._get_video_duration(post)
            if duration_seconds < min_duration:
                return False
                
        return True

    def download_reel(self, reel_url: str):
        """Download a single reel"""
        try:
            if "/reel/" not in reel_url:
                raise ValueError("Invalid reel URL")
                
            shortcode = reel_url.split("/reel/")[1].split("/")[0]
            post = instaloader.Post.from_shortcode(self.L.context, shortcode)
            download_path = os.path.join(os.getcwd(), "downloads", "instagram")
            os.makedirs(download_path, exist_ok=True)
            
            if self._is_already_downloaded(post.owner_username, shortcode):
                print(f"⏭️  Skipping reel (already downloaded)")
                return

            if not self._retry_download(post, download_path):
                raise Exception("Failed to download after maximum retries")
                
            print(f"✅ Successfully downloaded reel to {download_path}")
            
        except Exception as e:
            print(f"❌ Failed to download reel: {str(e)}")
            sys.exit(1)

    def download_user_reels(self, username: str, limit: Optional[int] = None, 
                          min_size_mb: Optional[float] = None, 
                          min_duration: Optional[float] = None):
        """Download reels from a user"""
        try:
            profile = instaloader.Profile.from_username(self.L.context, username)
            download_path = os.path.join(os.getcwd(), "downloads", "instagram", username)
            os.makedirs(download_path, exist_ok=True)
            
            print("📊 Analyzing reels...")
            eligible_reels = []
            skipped_count = 0
            already_downloaded = 0
            
            for post in profile.get_posts():
                if not post.is_video:
                    continue
                    
                if self._is_already_downloaded(username, post.shortcode):
                    already_downloaded += 1
                    continue
                    
                if self._meets_criteria(post, min_size_mb, min_duration):
                    eligible_reels.append(post)
                    if limit and len(eligible_reels) >= limit:
                        break
                else:
                    skipped_count += 1

            total_reels = len(eligible_reels)
            
            if total_reels == 0:
                print(f"❌ No new reels found matching criteria:")
                print(f"   - Already downloaded: {already_downloaded}")
                print(f"   - Skipped (didn't meet criteria): {skipped_count}")
                return
                
            print(f"📱 Found {total_reels} new reels matching criteria:")
            print(f"   - Already downloaded: {already_downloaded}")
            print(f"   - Skipped (didn't meet criteria): {skipped_count}")
            
            success_count = 0
            with tqdm(total=total_reels, desc="⬇️  Downloading reels", unit="reel") as pbar:
                for post in eligible_reels:
                    try:
                        size_mb = self._get_video_size_mb(post)
                        duration = self._get_video_duration(post)
                        
                        if self._retry_download(post, download_path):
                            success_count += 1
                            pbar.set_postfix(size=f"{size_mb:.1f}MB", duration=f"{duration:.1f}s")
                        else:
                            print(f"\n⚠️  Skipped reel {post.shortcode} after maximum retries")
                            
                        pbar.update(1)
                        time.sleep(self._get_random_delay())
                        
                    except Exception as e:
                        print(f"\n⚠️  Failed to download reel {post.shortcode}: {str(e)}")
                        continue
            
            print(f"\n✅ Downloaded {success_count} new reels to {download_path}")
            print(f"   Total reels for {username}: {success_count + already_downloaded}")
            
        except Exception as e:
            print(f"❌ Failed to download user reels: {str(e)}")
            sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description='Download Instagram Reels and TikTok Videos')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--url', '-r', help='URL of the Instagram reel')
    group.add_argument('--user', '-u', help='Username to download all reels from')
    group.add_argument('--tiktok', '-t', help='TikTok username or video URL')
    
    parser.add_argument('--login', action='store_true', help='Set up Instagram login credentials')
    parser.add_argument('--limit', '-l', type=int, help='Limit number of videos to download')
    parser.add_argument('--delay', '-d', type=float, default=3.0, 
                       help='Delay between downloads in seconds (default: 3.0, min: 1.0, max: 3.0)')
    parser.add_argument('--min-size', '-s', type=float,
                       help='Minimum size in megabytes (e.g., 30 for 30MB)')
    parser.add_argument('--min-duration', '-m', type=float,
                       help='Minimum duration in seconds (e.g., 120 for 2 minutes)')
    parser.add_argument('--retries', '-R', type=int, default=3,
                       help='Maximum number of retry attempts per video (default: 3)')
    parser.add_argument('--clear-history', action='store_true',
                       help='Clear download history before starting')
    
    args = parser.parse_args()

    if args.tiktok:
        downloader = TikTokDownloader(delay=args.delay, max_retries=args.retries)
        if args.clear_history:
            if os.path.exists(downloader.history_file):
                os.remove(downloader.history_file)
                print("🗑️  Download history cleared")
            downloader.downloaded_ids = {}
            
        # Check if it's a URL or username
        if 'tiktok.com' in args.tiktok:
            if '/video/' in args.tiktok:
                # Single video download
                downloader.download_single_video(args.tiktok)
            else:
                # User profile URL
                username = args.tiktok.split('@')[-1].split('/')[0]
                downloader.download_user_videos(username, args.limit)
        else:
            # Treat as username
            downloader.download_user_videos(args.tiktok, args.limit)
    else:
        # Handle Instagram downloads
        downloader = ReelsDownloader(delay=args.delay, max_retries=args.retries)
        
        if args.clear_history:
            if os.path.exists(downloader.history_file):
                os.remove(downloader.history_file)
                print("🗑️  Download history cleared")
            downloader.downloaded_shortcuts = {}
        
        if args.login:
            config = configparser.ConfigParser()
            config['Credentials'] = {
                'username': input('Enter Instagram username: '),
                'password': input('Enter Instagram password: ')
            }
            
            os.makedirs(os.path.dirname(downloader.config_file), exist_ok=True)
            
            with open(downloader.config_file, 'w') as configfile:
                config.write(configfile)
                os.chmod(downloader.config_file, 0o600)
                
            print("✅ Credentials saved successfully!")
            return

        if args.url:
            downloader.download_reel(args.url)
        elif args.user:
            downloader.download_user_reels(
                username=args.user,
                limit=args.limit,
                min_size_mb=args.min_size,
                min_duration=args.min_duration
            )

if __name__ == "__main__":
    main()