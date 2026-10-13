#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Earth Engine Data Downloader for vGeoInt_v2
Download data from Google Earth Engine
"""

import os
import sys
import argparse
import requests
from datetime import datetime
import ee


def log_progress(message):
    """Log progress message with timestamp"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] [INFO] {message}")


def log_error(message):
    """Log error message with timestamp"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] [ERROR] {message}")


class GEEDownloader:
    """Google Earth Engine Data Downloader Class"""

    def __init__(self, project_id):
        """
        Initialize the downloader with project ID.
        
        Args:
            project_id: Google Earth Engine project ID.
        """
        self.project_id = project_id
        log_progress(f"[INFO] Downloader initialized for project: {project_id}")

    def download_image(self, image_object, region, output_folder="downloads"):
        """
        Download image from Google Earth Engine.
        
        Args:
            image_object: ee.Image object to download.
            region: Region of interest as ee.Geometry.
            output_folder: Output folder path.
            
        Returns:
            str: Path to downloaded file.
        """
        try:
            # Create output directory if it doesn't exist
            os.makedirs(output_folder, exist_ok=True)
            log_progress(f"[OK] Output directory created: {output_folder}")

            # Get image ID for filename
            image_id_str = image_object.get("system:id").getInfo()
            log_progress(f"[INFO] Processing image: {image_id_str}")

            # Create shorter filename
            image_prefix = "_".join(image_id_str.split("/")[:2])
            filename = f"{image_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tif"
            filepath = os.path.join(output_folder, filename)

            log_progress(f"[INFO] Output filename: {filename}")

            # Get download URL using region parameter to crop image
            log_progress("[INFO] Creating download URL...")
            url = image_object.getDownloadUrl(
                {
                    "bands": ["B3", "B8", "B11"],
                    "region": region,
                    "scale": 20,
                    "format": "GEO_TIFF",
                }
            )
            log_progress(f"[OK] Download URL created successfully")

            # Download file to local machine
            log_progress(f"[INFO] Downloading {image_id_str}...")
            response = requests.get(url, stream=True)
            response.raise_for_status()

            with open(filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            log_progress(f"[OK] Downloaded successfully: {filepath}")
            return filepath

        except Exception as e:
            log_error(f"[ERROR] Download error: {e}")
            raise


def main():
    """Main function to run the program"""
    parser = argparse.ArgumentParser(
        description="Google Earth Engine Data Downloader - Windows Console Compatible"
    )
    parser.add_argument(
        "--data_id", required=True, help="Data ID from Google Earth Engine"
    )
    parser.add_argument(
        "--region",
        required=True,
        help="Region of interest (minLon,minLat,maxLon,maxLat)",
    )
    parser.add_argument("--output", default="downloads", help="Output folder path")
    parser.add_argument(
        "--project_id", default="root-clover-471000-e0", help="GEE Project ID"
    )

    args = parser.parse_args()

    log_progress("=== vGeoInt_v2 GEE Download Started ===")
    log_progress("Script version: 1.0 (Windows Console Compatible)")
    log_progress(f"Data ID: {args.data_id}")
    log_progress(f"Region: {args.region}")
    log_progress(f"Output folder: {args.output}")
    log_progress(f"Project ID: {args.project_id}")

    try:
        # Initialize GEE connection with project
        log_progress("[INFO] Initializing Google Earth Engine connection with project...")
        try:
            ee.Initialize(project=args.project_id)
            log_progress(f"[OK] Connected to GEE with project: {args.project_id}")
        except Exception as e:
            log_error(f"[ERROR] Cannot connect to project {args.project_id}: {e}")
            log_error("[ERROR] Please check Project ID and access permissions")
            sys.exit(1)

        # Parse region coordinates
        try:
            coords = [float(x.strip()) for x in args.region.split(",")]
            if len(coords) != 4:
                raise ValueError("Region must have exactly 4 coordinates")
            min_lon, min_lat, max_lon, max_lat = coords
            region = ee.Geometry.BBox(min_lon, min_lat, max_lon, max_lat)
            log_progress(
                f"[OK] Region parsed successfully: {min_lon}, {min_lat}, {max_lon}, {max_lat}"
            )
        except Exception as e:
            log_error(f"[ERROR] Invalid region format: {e}")
            log_error("Expected format: minLon,minLat,maxLon,maxLat")
            sys.exit(1)

        # Get image by ID
        log_progress(f"[INFO] Getting image with ID: {args.data_id}")
        try:
            filtered_image = ee.Image(args.data_id)
            # Verify image exists
            image_id = filtered_image.get("system:id").getInfo()
            if not image_id:
                log_error(f"[ERROR] Image not found with ID: {args.data_id}")
                sys.exit(1)
            log_progress(f"[OK] Image found: {image_id}")
        except Exception as e:
            log_error(f"[ERROR] Error getting image: {e}")
            log_error("[ERROR] Please check Data ID and access permissions")
            sys.exit(1)

        # Download image
        log_progress("[INFO] Starting image download...")
        try:
            downloader = GEEDownloader(args.project_id)
            downloaded_file = downloader.download_image(
                filtered_image, region, args.output
            )
            log_progress(
                f"[OK] Completed! File downloaded successfully to: {downloaded_file}"
            )
        except Exception as e:
            log_error(f"[ERROR] Error downloading image: {e}")
            log_error("[ERROR] Please check information and try again")
            sys.exit(1)

        log_progress("=== Process Finished ===")

    except KeyboardInterrupt:
        log_error("[ERROR] Process interrupted by user")
        sys.exit(1)
    except Exception as e:
        log_error(f"[ERROR] Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
