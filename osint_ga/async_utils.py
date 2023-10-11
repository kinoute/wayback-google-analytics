import asyncio
import re
from osint_ga.codes import get_UA_code, get_GA_code, get_GTM_code
from osint_ga.utils import get_date_from_timestamp, DEFAULT_HEADERS

# Semaphore to limit number of concurrent requests (10-15 appears to work fine. 20+ causes 443 error from web.archive.org)
sem = asyncio.Semaphore(10)


async def get_snapshot_timestamps(
    session,
    url,
    start_date,
    end_date,
    frequency,
    limit,
):
    """Takes a url and returns an array of snapshot timestamps for a given time range.

    Args:
        session (aiohttp.ClientSession)
        url (str)
        start_date (str, optional): Start date for time range. Defaults to Oct 1, 2012, when UA codes were adopted.
        end_date (str, optional): End date for time range.
        frequency (str, optional): Can limit snapshots to remove duplicates (1 per hr, day, week, etc).
        limit (int, optional): Limit number of snapshots returned.

    Returns:
        Array of timestamps:
            ["20190101000000", "20190102000000", ...]
    """

    # Default params get snapshots from url domain w/ 200 status codes only.
    cdx_url = f"http://web.archive.org/cdx/search/cdx?url={url}&matchType=domain&filter=statuscode:200&fl=timestamp&output=JSON"

    # Add correct params to cdx_url
    if frequency:
        cdx_url += f"&collapse=timestamp:{frequency}"

    if limit:
        cdx_url += f"&limit={limit}"

    if start_date:
        cdx_url += f"&from={start_date}"

    if end_date:
        cdx_url += f"&to={end_date}"

    print("CDX url: ", cdx_url)

    # Regex pattern to find 14-digit timestamps
    pattern = re.compile(r"\d{14}")

    # Use session to get timestamps
    async with session.get(cdx_url, headers=DEFAULT_HEADERS) as response:
        timestamps = pattern.findall(await response.text())

    print("Timestamps from CDX api: ", timestamps)

    # Return sorted timestamps
    return sorted(timestamps)


async def get_codes_from_snapshots(session, url, timestamps):
    """Returns an array of UA/GA codes for a given url using the Archive.org Wayback Machine.

    Args:
        session (aiohttp.ClientSession)
        url (str)
        timestamps (list): List of timestamps to get codes from.

    Returns:
        {
            "UA_codes": {
                "UA-12345678-1": {
                    "first_seen": "20190101000000",
                    "last_seen": "20190101000000"
                },
            "GA_codes": {
                "G-1234567890": {
                    "first_seen": "20190101000000",
                    "last_seen": "20190101000000"
                    },
                },
            "GTM_codes": {
                "GTM-1234567890": {
                    "first_seen": "20190101000000",
                    "last_seen": "20190101000000"
                    },
                },
        }
    """

    # Build base url template for wayback machine
    base_url = "https://web.archive.org/web/{timestamp}/" + url

    # Initialize results
    results = {
        "UA_codes": {},
        "GA_codes": {},
        "GTM_codes": {},
    }

    # Get codes from each timestamp with asyncio.gather().
    tasks = [
        get_codes_from_single_timestamp(session, base_url, timestamp, results)
        for timestamp in timestamps
    ]
    await asyncio.gather(*tasks)

    for code_type in results:
        for code in results[code_type]:
            results[code_type][code]["first_seen"] = get_date_from_timestamp(
                results[code_type][code]["first_seen"]
            )
            results[code_type][code]["last_seen"] = get_date_from_timestamp(
                results[code_type][code]["last_seen"]
            )

    return results


async def get_codes_from_single_timestamp(session, base_url, timestamp, results):
    """Returns UA/GA codes from a single archive.org snapshot and adds it to the results dictionary.

    Args:
        session (aiohttp.ClientSession)
        base_url (str): Base url for archive.org snapshot.
        timestamp (str): 14-digit timestamp.
        results (dict): Dictionary to add codes to (inherited from get_codes_from_snapshots()).

    Returns:
        None
    """

    # Use semaphore to limit number of concurrent requests
    async with sem:
        async with session.get(
            base_url.format(timestamp=timestamp), headers=DEFAULT_HEADERS
        ) as response:
            try:
                html = await response.text()

                print(
                    "Retrieving codes from url: ", base_url.format(timestamp=timestamp)
                )

                if html:
                    # Get UA/GA codes from html
                    UA_codes = get_UA_code(html)
                    GA_codes = get_GA_code(html)
                    GTM_codes = get_GTM_code(html)

                    # above functions return lists, so iterate thru codes and update
                    # results dict
                    for code in UA_codes:
                        if code not in results["UA_codes"]:
                            results["UA_codes"][code] = {}
                            results["UA_codes"][code]["first_seen"] = timestamp
                            results["UA_codes"][code]["last_seen"] = timestamp

                        if code in results["UA_codes"]:
                            if timestamp < results["UA_codes"][code]["first_seen"]:
                                results["UA_codes"][code]["first_seen"] = timestamp
                            if timestamp > results["UA_codes"][code]["last_seen"]:
                                results["UA_codes"][code]["last_seen"] = timestamp

                    for code in GA_codes:
                        if code not in results["GA_codes"]:
                            results["GA_codes"][code] = {}
                            results["GA_codes"][code]["first_seen"] = timestamp
                            results["GA_codes"][code]["last_seen"] = timestamp

                        if code in results["GA_codes"]:
                            if timestamp < results["GA_codes"][code]["first_seen"]:
                                results["GA_codes"][code]["first_seen"] = timestamp
                            if timestamp > results["GA_codes"][code]["last_seen"]:
                                results["GA_codes"][code]["last_seen"] = timestamp

                    for code in GTM_codes:
                        if code not in results["GTM_codes"]:
                            results["GTM_codes"][code] = {}
                            results["GTM_codes"][code]["first_seen"] = timestamp
                            results["GTM_codes"][code]["last_seen"] = timestamp

                        if code in results["GTM_codes"]:
                            if timestamp < results["GTM_codes"][code]["first_seen"]:
                                results["GTM_codes"][code]["first_seen"] = timestamp
                            if timestamp > results["GTM_codes"][code]["last_seen"]:
                                results["GTM_codes"][code]["last_seen"] = timestamp

            except Exception as e:
                print(
                    f"Error retrieving codes from {base_url.format(timestamp=timestamp)}: ",
                    e,
                )
                return None

        print("Finish gathering codes for: ", base_url.format(timestamp=timestamp))