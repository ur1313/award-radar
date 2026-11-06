# Award Radar

Free, regularly updated list of recent U.S. federal **contract awards** from USASpending.gov so small businesses can see who won what in their NAICS and state — competitive intel and teaming partners. Distinct from Bid Radar (open SAM.gov solicitations) and Grant Radar (Grants.gov nonprofit grants).

- Live site: https://ur1313.github.io/award-radar/
- Data: USASpending.gov public API `/api/v2/search/spending_by_award/` (no API key; award types A/B/C/D)
- Rebuild: `python3 build.py`
- Publish: `./deploy.sh`

Pro: $49/mo weekly digest filtered by NAICS + state. Wire a Stripe Payment Link into `PRO_URL` before rebuild.
