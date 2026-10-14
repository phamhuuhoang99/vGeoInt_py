#!/usr/bin/env python3
"""Download Sentinel-2 / Landsat / Sentinel-1 / Copernicus DEM for free from Microsoft Planetary Computer.

No account: the STAC API is public and the read tokens for the cloud-optimized GeoTIFFs are anonymous.
Only the region is read (HTTP range requests through GDAL /vsicurl/), reprojected to the UTM zone of the
region at --scale metres and written as one GeoTIFF. Runs with the GUI environment (GDAL + stdlib only),
so it works without the AI add-on.

    --list                          list matching items (least cloudy first)
    --data_id ITEM                  one STAC item (from --list)
    --method least_cloudy|mosaic    best item (+ the other tiles of the same day to cover the region),
                                    or all items newest on top
"""

import argparse
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime

from osgeo import gdal, osr

try:
    from vgeoint.ai.scripts._events import progress, result
except ImportError:  # stand-alone run outside the app
    def progress(*a, **k):
        pass

    def result(*a, **k):
        pass

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
TOKEN = "https://planetarycomputer.microsoft.com/api/sas/v1/token/{account}/{container}"
LIST_LIMIT = 50
MAX_ITEMS = 12  # items merged by a mosaic

gdal.UseExceptions()
for key, value in {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF,.tiff",
    "GDAL_HTTP_MAX_RETRY": "4",
    "GDAL_HTTP_RETRY_DELAY": "2",
    "VSI_CACHE": "TRUE",
}.items():
    gdal.SetConfigOption(key, value)


def log(level, message):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [{level}] {message}", flush=True)


def http_json(url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def parse_region(text):
    x0, y0, x1, y1 = (float(v) for v in text.split(","))
    if x0 >= x1 or y0 >= y1:
        raise ValueError("min must be smaller than max")
    return x0, y0, x1, y1


def search(args, bbox, limit):
    body = {"collections": [args.collection], "bbox": list(bbox), "limit": limit}
    if args.start and args.end:
        body["datetime"] = f"{args.start}T00:00:00Z/{args.end}T00:00:00Z"
    query = {}
    if args.max_cloud is not None:
        query["eo:cloud_cover"] = {"lte": args.max_cloud}
    if args.platform:
        query["platform"] = {"in": args.platform.split(",")}
    if query:
        body["query"] = query
    if args.max_cloud is not None:
        body["sortby"] = [{"field": "eo:cloud_cover", "direction": "asc"}]
    else:
        body["sortby"] = [{"field": "datetime", "direction": "desc"}]
    answer = http_json(f"{STAC}/search", body)
    total = answer.get("numberMatched") or answer.get("context", {}).get("matched")
    return answer.get("features", []), total


def item_date(item):
    return (item["properties"].get("datetime") or item["properties"].get("start_datetime") or "")[:16].replace("T", " ")


def utm_epsg(lon, lat):
    zone = int((lon + 180) // 6) + 1
    return (32600 if lat >= 0 else 32700) + zone


_tokens = {}


def signed(href):
    """/vsicurl/ path with the anonymous read token of the blob container holding the file."""
    parsed = urllib.parse.urlparse(href)
    account = parsed.netloc.split(".")[0]
    container = parsed.path.lstrip("/").split("/")[0]
    key = (account, container)
    if key not in _tokens:
        _tokens[key] = http_json(TOKEN.format(account=account, container=container))["token"]
    return "/vsicurl/" + href + ("&" if "?" in href else "?") + _tokens[key]


def pick_items(args, bbox):
    if args.data_id:
        item = http_json(f"{STAC}/collections/{args.collection}/items/{args.data_id}")
        return [item], item["id"]
    items, _ = search(args, bbox, 100)
    if not items:
        raise RuntimeError("No image matches the dates / cloud cover / region")
    log("OK", f"{len(items)} image(s) match")
    if args.method == "mosaic":
        chosen = sorted(items, key=lambda i: item_date(i), reverse=True)[:MAX_ITEMS]
        return chosen, f"mosaic of {len(chosen)} images"
    best = items[0]
    day = item_date(best)[:10]
    # The other tiles taken the same day (same orbit) complete the region; best one on top.
    same_day = [i for i in items[1:] if item_date(i)[:10] == day][: MAX_ITEMS - 1]
    return [best, *same_day], best["id"]


def download(args, bbox, items, label):
    bands = [b.strip() for b in args.bands.split(",") if b.strip()]
    lon, lat = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(utm_epsg(lon, lat))
    wgs84 = osr.SpatialReference()
    wgs84.ImportFromEPSG(4326)
    wgs84.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    x0, y0, x1, y1 = osr.CoordinateTransformation(wgs84, srs).TransformBounds(*bbox, 21)
    scale = args.scale
    x0, y0 = math.floor(x0 / scale) * scale, math.floor(y0 / scale) * scale
    x1, y1 = math.ceil(x1 / scale) * scale, math.ceil(y1 / scale) * scale

    os.makedirs(args.output, exist_ok=True)
    name = "".join(c if c.isalnum() or c in "-_" else "_" for c in (args.name or label))[:80]
    path = os.path.join(args.output, f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tif")
    out = None
    for b, band in enumerate(bands, 1):
        sources = []
        for item in reversed(items):  # gdal.Warp paints later sources on top: best item last
            asset = item["assets"].get(band)
            if asset is None:
                raise RuntimeError(f"Band {band} not in {item['id']} (bands: {', '.join(sorted(item['assets']))})")
            sources.append(signed(asset["href"]))
        log("INFO", f"Reading band {band} from {len(sources)} file(s)...")
        progress(100 * (b - 1) / len(bands), f"Kênh {band}")
        mem = gdal.Warp(
            "", sources, format="MEM", dstSRS=srs.ExportToWkt(), outputBounds=(x0, y0, x1, y1),
            xRes=scale, yRes=scale, resampleAlg="bilinear" if args.collection != "cop-dem-glo-30" else "cubic",
            multithread=True,
        )
        band_in = mem.GetRasterBand(1)
        if out is None:
            out = gdal.GetDriverByName("GTiff").Create(
                path, mem.RasterXSize, mem.RasterYSize, len(bands), band_in.DataType,
                options=["COMPRESS=DEFLATE", "TILED=YES", "BIGTIFF=IF_SAFER"],
            )
            out.SetGeoTransform(mem.GetGeoTransform())
            out.SetProjection(mem.GetProjection())
        band_out = out.GetRasterBand(b)
        band_out.WriteArray(band_in.ReadAsArray())
        band_out.SetDescription(band)
        nodata = band_in.GetNoDataValue()
        if nodata is not None:
            band_out.SetNoDataValue(nodata)
        mem = None
    out.FlushCache()
    out = None
    progress(100, "Xong")
    return path


def main():
    parser = argparse.ArgumentParser(description="Free imagery download from Microsoft Planetary Computer")
    parser.add_argument("--region", required=True, help="minLon,minLat,maxLon,maxLat (WGS 84)")
    parser.add_argument("--collection", required=True, help="STAC collection, e.g. sentinel-2-l2a")
    parser.add_argument("--output", default="downloads")
    parser.add_argument("--data_id", help="One STAC item ID")
    parser.add_argument("--start", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", help="End date YYYY-MM-DD (exclusive)")
    parser.add_argument("--max_cloud", type=float, help="Maximum cloud cover (%%)")
    parser.add_argument("--platform", help="Comma-separated platforms, e.g. landsat-9")
    parser.add_argument("--method", choices=["least_cloudy", "mosaic"], default="least_cloudy")
    parser.add_argument("--bands", default="", help="Comma-separated asset names")
    parser.add_argument("--scale", type=float, default=10, help="Pixel size in metres")
    parser.add_argument("--name", help="Output file name prefix")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    log("INFO", f"Planetary Computer: {args.collection}, region {args.region}")
    try:
        bbox = parse_region(args.region)
    except Exception as e:
        log("ERROR", f"Invalid region: {e}")
        sys.exit(1)
    try:
        if args.list:
            items, total = search(args, bbox, LIST_LIMIT)
            images = [{"id": i["id"], "date": item_date(i), "cloud": i["properties"].get("eo:cloud_cover")}
                      for i in items]
            for image in images:
                if image["cloud"] is not None:
                    image["cloud"] = round(image["cloud"], 1)
            log("OK", f"Found {total or len(images)} image(s)")
            result(images=images, total=total or len(images))
            return
        if not args.bands:
            raise RuntimeError("--bands is required")
        items, label = pick_items(args, bbox)
        log("OK", f"Image: {label}")
        path = download(args, bbox, items, label)
        log("OK", f"Completed! File downloaded successfully to: {path}")
        result(output=os.path.abspath(path), image=label)
    except Exception as e:
        log("ERROR", str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
