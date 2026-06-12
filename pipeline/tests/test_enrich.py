"""Tests for pipeline.enrich — three-tier county resolution."""

import pytest

from pipeline.models import EventItem


class TestEnricher:
    def test_tier1_zip_lookup_known_zip(self, enricher):
        # 21701 is Frederick, MD
        event = EventItem(
            zip="21701", addr_full="797 E Patrick St, Frederick, MD 21701"
        )
        enriched = enricher.enrich(event)
        assert enriched.county == "Frederick"
        assert enriched.county_full == "Frederick County"
        assert enriched.state == "MD"

    def test_tier1_dc_zip(self, enricher):
        event = EventItem(
            zip="20001", addr_full="801 Mt Vernon Pl NW, Washington, DC 20001"
        )
        enriched = enricher.enrich(event)
        assert enriched.state == "DC"

    def test_tier1_nj_zip(self, enricher):
        # 07001 is Middlesex County, NJ (Avenel)
        event = EventItem(zip="07001", addr_full="100 Main St, Avenel, NJ 07001")
        enriched = enricher.enrich(event)
        assert enriched.state == "NJ"
        assert enriched.county != ""

    def test_tier2_county_name_scan_when_no_zip(self, enricher):
        event = EventItem(
            addr_full="Montgomery County Fairgrounds, 16 Chestnut St, Gaithersburg",
            venue="Montgomery County Fairgrounds",
            name="Montgomery County Fair",
        )
        enriched = enricher.enrich(event)
        assert enriched.county == "Montgomery"

    def test_tier3_city_lookup_when_no_zip_or_county_name(self, enricher):
        # Westminster, MD → Carroll County
        event = EventItem(
            addr_full="706 Agricultural Center Dr, Westminster, MD",
            state="MD",
        )
        enriched = enricher.enrich(event)
        assert enriched.county != "" or enriched.city != ""

    def test_county_suffix_stripped_from_county_field(self, enricher):
        event = EventItem(zip="21701", addr_full="Frederick, MD 21701")
        enriched = enricher.enrich(event)
        # county must not end with "County"
        assert not enriched.county.endswith("County")

    def test_county_full_retains_suffix(self, enricher):
        event = EventItem(zip="21701", addr_full="Frederick, MD 21701")
        enriched = enricher.enrich(event)
        assert (
            "County" in enriched.county_full
            or enriched.county_full == "District of Columbia"
        )

    def test_city_extracted_from_address(self, enricher):
        event = EventItem(
            zip="21701",
            addr_full="Frederick Fairgrounds, 797 E Patrick St, Frederick, MD 21701",
            venue="Frederick Fairgrounds",
        )
        enriched = enricher.enrich(event)
        assert enriched.city != ""

    def test_existing_county_not_overwritten_by_tier2(self, enricher):
        # If Tier 1 already resolved county, Tier 2 must not run
        event = EventItem(
            zip="21701",
            county="Frederick",
            county_full="Frederick County",
            state="MD",
            addr_full="Some Rd, Rockville, MD 20850",  # Rockville would give Montgomery
        )
        enriched = enricher.enrich(event)
        assert enriched.county == "Frederick"  # Tier 1 result preserved

    def test_unknown_zip_falls_through_to_tier2(self, enricher):
        # ZIP 99999 doesn't exist — should fall through
        event = EventItem(
            zip="99999",
            addr_full="Frederick County Fairgrounds, Somewhere, MD",
            name="Frederick County Fair",
        )
        enriched = enricher.enrich(event)
        # Should resolve via Tier 2 county name scan
        assert enriched.county == "Frederick"

    def test_tier1_baltimore_city_zip(self, enricher):
        event = EventItem(zip="21201", addr_full="Baltimore, MD 21201")
        enriched = enricher.enrich(event)
        assert enriched.county == "Baltimore City"
        assert enriched.county_full == "Baltimore City"

    def test_tier1_baltimore_county_zip(self, enricher):
        event = EventItem(zip="21093", addr_full="Towson, MD 21093")
        enriched = enricher.enrich(event)
        assert enriched.county == "Baltimore County"
        assert enriched.county_full == "Baltimore County"

    def test_tier1_st_louis_city_zip(self, enricher):
        event = EventItem(zip="63101", addr_full="St. Louis, MO 63101")
        enriched = enricher.enrich(event)
        assert enriched.county == "St. Louis City"
        assert enriched.county_full == "St. Louis City"

    def test_tier1_st_louis_county_zip(self, enricher):
        event = EventItem(zip="63105", addr_full="Clayton, MO 63105")
        enriched = enricher.enrich(event)
        assert enriched.county == "St. Louis"
        assert enriched.county_full == "St. Louis County"

    def test_tier1_alexandria_city_zip(self, enricher):
        event = EventItem(zip="22301", addr_full="Alexandria, VA 22301")
        enriched = enricher.enrich(event)
        assert enriched.county == "Alexandria City"
        assert enriched.county_full == "Alexandria City"

    def test_tier1_richmond_city_zip(self, enricher):
        event = EventItem(zip="23219", addr_full="Richmond, VA 23219")
        enriched = enricher.enrich(event)
        assert enriched.county == "Richmond City"
        assert enriched.county_full == "Richmond City"

    def test_tier1_dewitt_county_il(self, enricher):
        event = EventItem(zip="61727", addr_full="Clinton, IL 61727")
        enriched = enricher.enrich(event)
        assert enriched.county == "DeWitt"

    def test_tier2_baltimore_city_in_address(self, enricher):
        event = EventItem(
            addr_full="Baltimore City, MD",
            name="Baltimore City Home Show",
        )
        enriched = enricher.enrich(event)
        assert enriched.county == "Baltimore City"

    def test_tier2_baltimore_county_in_address(self, enricher):
        event = EventItem(
            addr_full="Baltimore County, MD",
            name="Baltimore County Fair",
        )
        enriched = enricher.enrich(event)
        assert enriched.county == "Baltimore County"
