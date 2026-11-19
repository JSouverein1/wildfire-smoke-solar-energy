"""Download daily NASA LAADS MCD06COSP_D3_MODIS NetCDF files.

Uses NASA LAADS day-directory JSON listings. Tries Python requests first and,
if NASA returns an HTML login/error page, retries with NASA's documented curl
redirect + cookie flow. Uses curl --config - so the token isn't in shell history
or process command-line arguments.

Usage (PowerShell):
    python scripts/download_laads_cosp.py --start 2020-09-10 --end 2020-09-10
    python scripts/download_laads_cosp.py --start 2020-09-10 --end 2020-09-10 --method curl

Get a fresh Earthdata bearer token at https://urs.earthdata.nasa.gov/profile
Never commit tokens to GitHub or share them in a chat.
"""

import argparse
import getpass
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote, urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = (
    "https://ladsweb.modaps.eosdis.nasa.gov/archive/allData/62/"
    "MCD06COSP_D3_MODIS"
)
PRODUCT = "MCD06COSP_D3_MODIS"


class HtmlInsteadOfData(RuntimeError):
    """NASA returned a login/error webpage instead of a NetCDF file."""


def days_between(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def _safe_redirect_summary(response):
    """Return status and host/path, never query strings or auth material."""
    hops = list(response.history) + [response]
    return " -> ".join(
        f"{hop.status_code} {urlsplit(hop.url).netloc}{urlsplit(hop.url).path}"
        for hop in hops
    )


def _looks_like_netcdf(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 8:
        return False
    with path.open("rb") as handle:
        signature = handle.read(8)
    return (
        signature.startswith((b"CDF\x01", b"CDF\x02", b"CDF\x05"))
        or signature.startswith(b"\x89HDF\r\n\x1a\n")
        or signature.startswith(b"\x0e\x03\x13\x01")
    )


def _download_requests(session: requests.Session, url: str, temp: Path):
    with session.get(url, stream=True, timeout=(20, 180)) as result:
        result.raise_for_status()
        content_type = result.headers.get("Content-Type", "").lower()
        if "text/html" in content_type:
            raise HtmlInsteadOfData(
                "NASA returned an HTML page rather than NetCDF. "
                "Redirect chain: " + _safe_redirect_summary(result)
            )
        length = result.headers.get("Content-Length")
        with temp.open("wb") as output:
            for chunk in result.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    output.write(chunk)
        if length is not None and temp.stat().st_size != int(length):
            raise RuntimeError(f"Incomplete download: {temp.name}")
        if not _looks_like_netcdf(temp):
            raise HtmlInsteadOfData(
                "The response did not have a recognizable NetCDF/HDF signature. "
                "Redirect chain: " + _safe_redirect_summary(result)
            )


def _download_curl(url: str, temp: Path, token: str):
    """Follow NASA's documented -L and cookie workflow without exposing token in argv."""
    curl = shutil.which("curl.exe") if sys.platform == "win32" else shutil.which("curl")
    if not curl:
        raise RuntimeError(
            "curl is not installed/found. On Windows, run `where.exe curl.exe` "
            "to check availability."
        )

    with tempfile.TemporaryDirectory(prefix="laads_auth_") as scratch:
        cookies = Path(scratch) / "session_cookies.txt"
        # Tokens and file paths are fed on stdin, not visible in command history.
        config = f'header = "Authorization: Bearer {token}"\nurl = "{url}"\n'
        completed = subprocess.run(
            [
                curl,
                "--config", "-",
                "--fail", "--location", "--silent", "--show-error",
                "--connect-timeout", "20", "--max-time", "600",
                "--retry", "2", "--retry-delay", "2",
                "--cookie", "", "--cookie-jar", str(cookies),
                "--output", str(temp),
            ],
            input=config,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "NASA/curl download failed (exit "
                + str(completed.returncode) + "). "
                + completed.stderr.strip()[:400]
                + "\nIf redirected to an Earthdata sign-in page, verify your NEW token "
                "and log in to the LAADS website once in your browser."
            )

    if not _looks_like_netcdf(temp):
        raise HtmlInsteadOfData(
            "curl completed, but NASA still returned a non-NetCDF file "
            f"({temp.stat().st_size if temp.exists() else 0} bytes). "
            "Check Earthdata authorization and whether you can download this "
            "file while logged in on the NASA website."
        )


def fetch_day(
    session: requests.Session,
    day: date,
    destination: Path,
    token: str,
    method: str = "auto",
) -> bool:
    folder_url = f"{ROOT}/{day.year}/{day.timetuple().tm_yday:03d}"
    index_url = folder_url + ".json"
    response = session.get(index_url, timeout=(20, 90))
    response.raise_for_status()
    try:
        listing = response.json()
    except ValueError as exc:
        raise RuntimeError(
            "Could not parse NASA's JSON listing: " + index_url + ". "
            "HTTP redirect chain: " + _safe_redirect_summary(response)
        ) from exc

    entries = listing.get("content", [])
    filenames = [
        entry["name"]
        for entry in entries
        if entry.get("name", "").startswith(
            f"{PRODUCT}.A{day.year}{day.timetuple().tm_yday:03d}."
        )
        and entry["name"].endswith(".nc")
    ]
    if not filenames:
        print(f"{day}: No NetCDF file listed; check data availability.")
        return False

    destination.mkdir(parents=True, exist_ok=True)
    for filename in filenames:
        output = destination / filename
        if output.exists() and _looks_like_netcdf(output):
            print(f"{day}: Already present: {filename}")
            continue

        url = f"{folder_url}/{quote(filename)}"
        temp = output.with_name(output.name + ".part")
        if temp.exists():
            temp.unlink()
        print(f"{day}: Downloading {filename}")
        try:
            if method == "curl":
                _download_curl(url, temp, token)
            else:
                try:
                    _download_requests(session, url, temp)
                except HtmlInsteadOfData as exc:
                    if method == "requests":
                        raise
                    print(f"NASA login/redirect detected: {exc}")
                    print("Retrying with curl's redirect + cookie handling...")
                    if temp.exists():
                        temp.unlink()
                    _download_curl(url, temp, token)
            temp.replace(output)
        finally:
            if temp.exists():
                temp.unlink()
        print(f"Saved {output} ({output.stat().st_size / 1e6:.1f} MB)")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Download MCD06COSP daily MODIS cloud NetCDF files from NASA LAADS"
    )
    parser.add_argument("--start", required=True, help="First day: YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="Last day: YYYY-MM-DD")
    parser.add_argument(
        "--output", default="data/raw/modis_cosp", help="Download folder"
    )
    parser.add_argument(
        "--method", choices=["auto", "requests", "curl"], default="auto",
        help="auto retries with curl if requests gets an HTML login/error page",
    )
    args = parser.parse_args()
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    if start > end:
        parser.error("--start must be on or before --end")

    token = (os.getenv("EARTHDATA_TOKEN") or getpass.getpass("Earthdata token: ")).strip()
    if not token:
        parser.error("An Earthdata token is required")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", token):
        parser.error(
            "The token contains unexpected characters (e.g., spaces, |, \\). "
            "Copy only the token characters from NASA's Earthdata profile."
        )

    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}"})
    retry = Retry(
        total=3, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504]
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))

    successes = 0
    total = 0
    for day in days_between(start, end):
        total += 1
        try:
            successes += bool(fetch_day(session, day, Path(args.output), token, args.method))
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in (401, 403):
                raise SystemExit(
                    f"NASA rejected the token (HTTP {status}). "
                    "Regenerate your Earthdata token and sign in to LAADS."
                ) from exc
            print(f"{day}: HTTP error ({exc}); proceeding to next day")
        except requests.RequestException as exc:
            print(f"{day}: Network error ({exc}); proceeding to next day")
        except (RuntimeError, OSError) as exc:
            raise SystemExit(f"{day}: {exc}") from exc

    print(f"Completed: found files for {successes} out of {total} requested days")


if __name__ == "__main__":
    main()
