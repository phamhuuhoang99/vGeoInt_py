#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Earth Engine Data Downloader for vGeoInt_v2

Two ways to pick the image (the old script only took one image ID and always downloaded B3,B8,B11):
- a collection (--collection) filtered by region, dates, cloud cover and property filters, reduced to the
  least cloudy image, a median composite or a mosaic (--method); --list only lists the matching images;
- one image by ID (--data_id), e.g. picked from a --list result.
"""

import argparse
import os
import sys
from datetime import datetime, timezone

import ee
import requests

try:
    from vgeoint.ai.scripts._events import result
except ImportError:  # stand-alone run outside the app
    def result(*a, **k):
        pass

LIST_LIMIT = 50


def log_progress(message):
    """Log progress message with timestamp"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] [INFO] {message}", flush=True)


def log_error(message):
    """Log error message with timestamp"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] [ERROR] {message}", flush=True)


def parse_region(text):
    coords = [float(x.strip()) for x in text.split(",")]
    if len(coords) != 4:
        raise ValueError("Region must have exactly 4 coordinates")
    min_lon, min_lat, max_lon, max_lat = coords
    if min_lon >= max_lon or min_lat >= max_lat:
        raise ValueError("min must be smaller than max")
    return min_lon, min_lat, max_lon, max_lat


def filtered_collection(args, region):
    collection = ee.ImageCollection(args.collection).filterBounds(region)
    if args.start and args.end:
        collection = collection.filterDate(args.start, args.end)
    if args.cloud_property and args.max_cloud is not None:
        collection = collection.filter(ee.Filter.lte(args.cloud_property, args.max_cloud))
    for item in args.filter or []:
        key, _, value = item.partition("=")
        collection = collection.filter(ee.Filter.eq(key, value))
    return collection


def list_images(args, region):
    """Matching images, least cloudy first (newest first without a cloud property)."""
    collection = filtered_collection(args, region)
    if args.cloud_property:
        collection = collection.sort(args.cloud_property)
    else:
        collection = collection.sort("system:time_start", False)
    properties = ["system:id", "system:time_start"] + ([args.cloud_property] if args.cloud_property else [])
    info = collection.limit(LIST_LIMIT).reduceColumns(ee.Reducer.toList(len(properties)), properties).getInfo()
    images = []
    for row in info.get("list", []):
        image_id, time_start = row[0], row[1]
        date = datetime.fromtimestamp(time_start / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M") if time_start else ""
        cloud = round(row[2], 1) if args.cloud_property and row[2] is not None else None
        images.append({"id": image_id, "date": date, "cloud": cloud})
    return images, collection.size().getInfo()


def reduce_collection(args, region):
    collection = filtered_collection(args, region)
    count = collection.size().getInfo()
    if count == 0:
        raise RuntimeError("No image matches the dates / cloud cover / region")
    log_progress(f"[OK] {count} image(s) match")
    if args.method == "median":
        return collection.median().clip(region), f"median of {count} images"
    if args.method == "mosaic":
        return collection.sort("system:time_start").mosaic().clip(region), f"mosaic of {count} images"
    key = args.cloud_property or "system:time_start"
    image = ee.Image(collection.sort(key, bool(args.cloud_property)).first())
    return image, image.get("system:id").getInfo()


def download(image, region, args, name):
    os.makedirs(args.output, exist_ok=True)
    filename = f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tif"
    filepath = os.path.join(args.output, filename)
    params = {"region": region, "scale": args.scale, "format": "GEO_TIFF"}
    if args.bands:
        params["bands"] = [b.strip() for b in args.bands.split(",") if b.strip()]
    log_progress("[INFO] Creating download URL...")
    url = image.getDownloadUrl(params)
    log_progress(f"[INFO] Downloading to {filepath} ...")
    response = requests.get(url, stream=True, timeout=600)
    response.raise_for_status()
    with open(filepath, "wb") as f:
        for chunk in response.iter_content(chunk_size=1 << 16):
            f.write(chunk)
    return filepath


def safe_name(text):
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in text).strip("_")[:80] or "gee"


def main():
    parser = argparse.ArgumentParser(description="Google Earth Engine Data Downloader")
    parser.add_argument("--project_id", required=True, help="Google Cloud project registered for Earth Engine")
    parser.add_argument("--region", required=True, help="minLon,minLat,maxLon,maxLat (WGS 84)")
    parser.add_argument("--output", default="downloads", help="Output folder path")
    parser.add_argument("--data_id", help="One image ID (instead of --collection)")
    parser.add_argument("--collection", help="ImageCollection ID")
    parser.add_argument("--start", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", help="End date YYYY-MM-DD (exclusive)")
    parser.add_argument("--cloud_property", help="Cloud cover property of the collection")
    parser.add_argument("--max_cloud", type=float, help="Maximum cloud cover (%%)")
    parser.add_argument("--filter", action="append", help="property=value filter (repeatable)")
    parser.add_argument("--method", choices=["least_cloudy", "median", "mosaic"], default="least_cloudy")
    parser.add_argument("--bands", help="Comma-separated bands (all bands when empty)")
    parser.add_argument("--scale", type=float, default=10, help="Pixel size in metres")
    parser.add_argument("--name", help="Output file name prefix")
    parser.add_argument("--list", action="store_true", help="Only list the matching images of --collection")
    parser.add_argument("--check", action="store_true", help="Only check that the project can use Earth Engine")
    args = parser.parse_args()
    if not args.check and not args.data_id and not args.collection:
        parser.error("--data_id or --collection is required")

    log_progress("=== vGeoInt GEE Download Started ===")
    log_progress(f"Project ID: {args.project_id}")
    log_progress(f"Region: {args.region}")
    log_progress(f"Image: {args.data_id or args.collection}")

    try:
        ee.Initialize(project=args.project_id)
        ee.Number(1).getInfo()  # Initialize alone does not check the project's permissions
        log_progress(f"[OK] Connected to Earth Engine with project: {args.project_id}")
        if args.check:
            result(project=args.project_id)
            return
    except Exception as e:
        log_error(f"Cannot connect to project {args.project_id}: {e}")
        log_error("Check the Project ID (Earth Engine must be enabled for it) or log in again")
        sys.exit(1)

    try:
        region = ee.Geometry.BBox(*parse_region(args.region))
    except Exception as e:
        log_error(f"Invalid region: {e}")
        sys.exit(1)

    try:
        if args.list:
            images, total = list_images(args, region)
            log_progress(f"[OK] Found {total} image(s)")
            result(images=images, total=total)
            return
        if args.data_id:
            image = ee.Image(args.data_id)
            label = image.get("system:id").getInfo()
        else:
            image, label = reduce_collection(args, region)
        log_progress(f"[OK] Image: {label}")
        if args.method == "median" and not args.data_id:
            image = image.toFloat()  # a median mixes integer types; one type per GeoTIFF
        filepath = download(image, region, args, safe_name(args.name or label))
        log_progress(f"[OK] Completed! File downloaded successfully to: {filepath}")
        result(output=os.path.abspath(filepath), image=label)
    except Exception as e:
        message = str(e)
        log_error(message)
        if "request size" in message.lower() or "must be less than or equal to" in message:
            log_error("Area too large for a direct download: increase the pixel size or reduce the region")
        sys.exit(1)


if __name__ == "__main__":
    main()
