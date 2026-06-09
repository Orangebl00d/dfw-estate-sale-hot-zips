# DFW Estate Sale Hot ZIP Codes

Shareable map of potential DFW estate sale target ZIP codes, ranked for high-end home density and likely estate-sale yield.

The live site is served with GitHub Pages from `index.html`.

## Weekend Reports

Generate a date-range estate sale plan:

```bash
python3 scripts/generate_estate_sale_report.py --start 2026-06-13 --end 2026-06-14
```

The script writes:

- `reports/dfw-YYYY-MM-DD-to-YYYY-MM-DD.html`
- `reports/dfw-YYYY-MM-DD-to-YYYY-MM-DD.md`
- `reports/latest.html`
- `data/reports/dfw-YYYY-MM-DD-to-YYYY-MM-DD.json`

Automated pulls use EstateSales.NET and EstateSales.org. The report also includes manual cross-check links for EstateSale.com, HiBid, AuctionNinja, and MaxSold.
