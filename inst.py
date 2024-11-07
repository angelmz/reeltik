#!/usr/bin/env python3

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
from urllib.parse import urlparse
import json
import glob

class ReelsDownloader:
    def __init__(self, delay: float = 3.0, max_retries: int = 3):
        self.delay = delay
        self.max_retries = max_retries
        self.config_file = os.path.expanduser('~/.config/inst/config.ini')
        self.history_file = os.path.expanduser('~/.config/inst/download_history.json')
        
        self.L = instaloader.Instaloader(
            download_videos=True,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=True,
            download_pictures=False
        )
        
        # Initialize after defining paths
        self.downloaded_shortcuts = self._load_history()
        self._load_config()

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

    def _get_video_size_mb(self, post) -> float:
        """Get video size in megabytes"""
        try:
            response = self.L.context.get_json(f"https://www.instagram.com/p/{post.shortcode}/?__a=1")
            video_url = response['graphql']['shortcode_media']['video_url']
            size_bytes = int(self.L.context.head(video_url).headers.get('content-length', 0))
            return size_bytes / (1024 * 1024)
        except Exception:
            try:
                video_url = post.video_url
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
        try:
            if min_size is not None:
                size_mb = self._get_video_size_mb(post)
                if size_mb < min_size:
                    return False
                    
            if min_duration is not None:
                duration_seconds = self._get_video_duration(post)
                if duration_seconds < min_duration:
                    return False
                    
            return True
        except Exception as e:
            print(f"\n⚠️  Error checking criteria for {post.shortcode}: {str(e)}")
            return False

    def _retry_download(self, post, target_path: str) -> bool:
        """Retry download with fresh URL"""
        for attempt in range(self.max_retries):
            try:
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
                time.sleep(self.delay * (attempt + 1))
                
        return False

    def download_reel(self, reel_url):
        """Download a single reel by URL"""
        try:
            if "/reel/" not in reel_url:
                raise ValueError("Invalid reel URL")
                
            shortcode = reel_url.split("/reel/")[1].split("/")[0]
            post = instaloader.Post.from_shortcode(self.L.context, shortcode)
            
            if self._is_already_downloaded(post.owner_username, shortcode):
                print(f"✅ Reel already downloaded")
                return
            
            download_path = os.path.join(os.getcwd(), "downloads")
            os.makedirs(download_path, exist_ok=True)
            
            if not self._retry_download(post, download_path):
                raise Exception("Failed to download after maximum retries")
                
            print(f"✅ Successfully downloaded reel to {download_path}")
            
        except Exception as e:
            print(f"❌ Failed to download reel: {str(e)}")
            sys.exit(1)

    def download_user_reels(self, username: str, limit: Optional[int] = None, 
                          min_size_mb: Optional[float] = None, 
                          min_duration: Optional[float] = None):
        """Download reels from a user with filters"""
        try:
            profile = instaloader.Profile.from_username(self.L.context, username)
            download_path = os.path.join(os.getcwd(), "downloads", username)
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
                        time.sleep(self.delay)
                        
                    except Exception as e:
                        print(f"\n⚠️  Failed to download reel {post.shortcode}: {str(e)}")
                        continue
            
            print(f"\n✅ Downloaded {success_count} new reels to {download_path}")
            print(f"   Total reels for {username}: {success_count + already_downloaded}")
            
        except Exception as e:
            print(f"❌ Failed to download user reels: {str(e)}")
            sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description='Download Instagram Reels')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--url', '-r', help='URL of the Instagram reel')
    group.add_argument('--user', '-u', help='Username to download all reels from')
    parser.add_argument('--login', action='store_true', help='Set up login credentials')
    parser.add_argument('--limit', '-l', type=int, help='Limit number of reels to download')
    parser.add_argument('--delay', '-d', type=float, default=3.0, 
                       help='Delay between downloads in seconds (default: 3.0)')
    parser.add_argument('--min-size', '-s', type=float,
                       help='Minimum size in megabytes (e.g., 30 for 30MB)')
    parser.add_argument('--min-duration', '-t', type=float,
                       help='Minimum duration in seconds (e.g., 120 for 2 minutes)')
    parser.add_argument('--retries', '-R', type=int, default=3,
                       help='Maximum number of retry attempts per reel (default: 3)')
    parser.add_argument('--clear-history', action='store_true',
                       help='Clear download history before starting')
    
    args = parser.parse_args()
    
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