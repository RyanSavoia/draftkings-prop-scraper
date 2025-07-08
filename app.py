import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template_string
from flask_cors import CORS
import re
import os
from datetime import datetime, timedelta

app = Flask(__name__)

# Add CORS configuration
CORS(app, origins=[
   "https://thebettinginsider.com",
   "https://www.thebettinginsider.com",
   "http://localhost:3000",
   "http://127.0.0.1:3000"
])

# Global variables to store scraped data and timestamp
cached_props_data = []
cache_timestamp = None
CACHE_DURATION_MINUTES = 30  # Cache expires after 30 minutes

def is_cache_expired():
   """Check if cache has expired"""
   global cache_timestamp
   if cache_timestamp is None:
       return True
   
   now = datetime.now()
   cache_age = now - cache_timestamp
   return cache_age > timedelta(minutes=CACHE_DURATION_MINUTES)

def get_cached_or_fresh_data():
   """Get cached data if available and not expired, otherwise scrape fresh data"""
   global cached_props_data, cache_timestamp
   
   if cached_props_data and not is_cache_expired():
       print(f"Using cached data (age: {datetime.now() - cache_timestamp})...")
       return cached_props_data
   else:
       print("Cache expired or empty, scraping fresh data...")
       fresh_data = scrape_player_props()
       cached_props_data = fresh_data
       cache_timestamp = datetime.now()
       return fresh_data

def convert_bet_line(bet_line):
   """Convert '1+' to 'Over 0.5', '2+' to 'Over 1.5', etc."""
   if not bet_line:
       return bet_line
   
   # Check if it matches the pattern "number+"
   match = re.match(r'^(\d+)\+$', bet_line.strip())
   if match:
       number = int(match.group(1))
       return f"Over {number - 0.5}"
   
   return bet_line

def scrape_player_props():
   """Scrape player props from DraftKings - all active sports for today and tomorrow"""
   base_url = "https://dknetwork.draftkings.com/draftkings-sportsbook-player-props/"
   
   # Sport IDs and configurations
   sport_configs = {
       'mlb': {'id': 84240, 'name': 'MLB', 'date_ranges': ['today', 'tomorrow']},
       'wnba': {'id': 94682, 'name': 'WNBA', 'date_ranges': ['today', 'tomorrow']},
       'nba': {'id': 42648, 'name': 'NBA', 'date_ranges': ['today', 'tomorrow']},
       'nhl': {'id': 42133, 'name': 'NHL', 'date_ranges': ['today', 'tomorrow']},
       'nfl': {'id': 88808, 'name': 'NFL', 'date_ranges': ['today', 'tomorrow']},
       'ufc': {'id': 9034, 'name': 'UFC', 'date_ranges': ['today', 'tomorrow']},
       'ncaaf': {'id': 87637, 'name': 'NCAA Football', 'date_ranges': ['today', 'tomorrow']},
       'ncaa_basketball': {'id': 92483, 'name': 'NCAA Basketball', 'date_ranges': ['today', 'tomorrow']},
       'ncaa_womens_basketball': {'id': 36647, 'name': 'NCAA Womens Basketball', 'date_ranges': ['today', 'tomorrow']},
       'ncaa_baseball': {'id': 41151, 'name': 'NCAA Baseball', 'date_ranges': ['today', 'tomorrow']},
       'ncaa_ice_hockey': {'id': 84813, 'name': 'NCAA Ice Hockey', 'date_ranges': ['today', 'tomorrow']},
       'mls': {'id': 89345, 'name': 'MLS', 'date_ranges': ['today']},  # Soccer: today only
       'premier_league': {'id': 40253, 'name': 'England Premier League', 'date_ranges': ['today']},
       'champions_league': {'id': 40685, 'name': 'Champions League', 'date_ranges': ['today']},
       'europa_league': {'id': 41410, 'name': 'Europa League', 'date_ranges': ['today']},
   }
   
   all_props_data = []
   
   print("Scraping player props for all sports...")
   
   # Scrape each sport for both today and tomorrow
   for sport_name, config in sport_configs.items():
       sport_id = config['id']
       sport_display_name = config['name']
       date_ranges = config['date_ranges']
       
       print(f"Scraping {sport_display_name} (ID: {sport_id})...")
       sport_total_props = 0
       
       # Loop through each date range for this sport (today, tomorrow)
       for date_range in date_ranges:
           print(f"  Scraping {sport_display_name} for {date_range}...")
           
           try:
               # Build URL with sport ID, date, and view=2 for "Most Bet Player Props"
               url = f"{base_url}?tb_eg={sport_id}&tb_edate={date_range}&tb_view=2"
               
               print(f"    Fetching URL: {url}")
               response = requests.get(url)
               response.raise_for_status()
               soup = BeautifulSoup(response.content, 'html.parser')
               
               # Find the props table
               props_table = soup.find('table', class_='tb_pp_table')
               
               if not props_table:
                   print(f"    No props table found for {sport_display_name} on {date_range}")
                   continue
               
               # Find all table rows (excluding header)
               rows = props_table.find('tbody')
               if not rows:
                   print(f"    No tbody found for {sport_display_name} on {date_range}")
                   continue
               
               prop_rows = rows.find_all('tr')
               print(f"    Found {len(prop_rows)} prop rows for {sport_display_name} on {date_range}")
               
               for row in prop_rows:
                   prop_data = parse_prop_row(row, sport_display_name, date_range)
                   if prop_data:
                       # Check for duplicates
                       duplicate = any(
                           existing['event'] == prop_data['event'] and
                           existing['event_date'] == prop_data['event_date'] and
                           existing['market'] == prop_data['market'] and
                           existing['betslip_line'] == prop_data['betslip_line'] and
                           existing['scraped_date_range'] == prop_data['scraped_date_range']
                           for existing in all_props_data
                       )
                       
                       if not duplicate:
                           all_props_data.append(prop_data)
                           sport_total_props += 1
                       else:
                           print(f"        Skipping duplicate: {prop_data['market']} - {prop_data['betslip_line']}")
                   
           except Exception as e:
               print(f"    Error scraping {sport_display_name} for {date_range}: {e}")
               continue
       
       print(f"  Total props found for {sport_display_name}: {sport_total_props}")
       print()
   
   print(f"Total unique props scraped: {len(all_props_data)}")
   return all_props_data

def parse_prop_row(row, sport_name, date_range):
   """Parse individual prop row from the table"""
   try:
       cells = row.find_all('td')
       
       if len(cells) < 5:
           print(f"    Row has fewer than 5 cells: {len(cells)}")
           return None
       
       # Extract data from cells
       event = cells[0].text.strip()
       event_date = cells[1].text.strip()
       market = cells[2].text.strip()
       betslip_line = cells[3].text.strip()
       
       # Convert betslip line (1+ -> Over 0.5, 2+ -> Over 1.5, etc.)
       converted_betslip_line = convert_bet_line(betslip_line)
       
       # Extract odds and link
       odds_cell = cells[4]
       odds_link = odds_cell.find('a')
       
       if odds_link:
           odds = odds_link.text.strip()
           draftkings_url = odds_link.get('href', '')
       else:
           odds = odds_cell.text.strip()
           draftkings_url = ''
       
       prop_data = {
           'event': event,
           'event_date': event_date,
           'market': market,
           'betslip_line': betslip_line,
           'converted_betslip_line': converted_betslip_line,
           'odds': odds,
           'draftkings_url': draftkings_url,
           'sport': sport_name,
           'scraped_date_range': date_range,
           'scraped_timestamp': datetime.now().isoformat()
       }
       
       print(f"        Parsed prop: {market} - {betslip_line} ({odds})")
       return prop_data
       
   except Exception as e:
       print(f"    Error parsing prop row: {e}")
       return None

def filter_by_sport(props, sport_name):
   """Filter props by sport"""
   return [prop for prop in props if prop['sport'].lower() == sport_name.lower()]

def get_top_props_by_sport(props, limit=10):
   """Get top props grouped by sport"""
   sports_props = {}
   
   for prop in props:
       sport = prop['sport']
       if sport not in sports_props:
           sports_props[sport] = []
       sports_props[sport].append(prop)
   
   # Limit each sport to top N props
   for sport in sports_props:
       sports_props[sport] = sports_props[sport][:limit]
   
   return sports_props

# Flask routes
@app.route('/')
def home():
   cache_status = f"Cache: {'Active' if cached_props_data else 'Empty'}"
   if cache_timestamp:
       cache_age = datetime.now() - cache_timestamp
       cache_status += f" (Age: {cache_age})"
   
   return f"""
   <h1>DraftKings Player Props Scraper</h1>
   <p><strong>{cache_status}</strong></p>
   <p>Cache Duration: {CACHE_DURATION_MINUTES} minutes</p>
   <h2>Data Endpoints:</h2>
   <ul>
       <li><a href="/all-props">/all-props</a> - All player props</li>
       <li><a href="/mlb-props">/mlb-props</a> - MLB props only</li>
       <li><a href="/wnba-props">/wnba-props</a> - WNBA props only</li>
       <li><a href="/nba-props">/nba-props</a> - NBA props only</li>
       <li><a href="/nfl-props">/nfl-props</a> - NFL props only</li>
       <li><a href="/nhl-props">/nhl-props</a> - NHL props only</li>
       <li><a href="/ufc-props">/ufc-props</a> - UFC props only</li>
       <li><a href="/top-props-by-sport">/top-props-by-sport</a> - Top 10 props per sport</li>
       <li><a href="/test-props">/test-props</a> - Test endpoint (first 5 props)</li>
   </ul>
   <h2>Cache Management:</h2>
   <ul>
       <li><a href="/refresh-props-cache">/refresh-props-cache</a> - Force refresh the props cache</li>
   </ul>
   <h2>Analytics:</h2>
   <ul>
       <li><a href="/props-summary">/props-summary</a> - Summary of all props by sport</li>
       <li><a href="/converted-lines">/converted-lines</a> - Props with converted bet lines (1+ -> Over 0.5)</li>
   </ul>
   """

@app.route('/all-props')
def get_all_props():
   """Get all player props"""
   props = get_cached_or_fresh_data()
   return jsonify({
       'props': props,
       'count': len(props),
       'cached': bool(cached_props_data),
       'cache_age_minutes': (datetime.now() - cache_timestamp).total_seconds() / 60 if cache_timestamp else 0
   })

@app.route('/mlb-props')
def get_mlb_props():
   """Get MLB player props only"""
   all_props = get_cached_or_fresh_data()
   mlb_props = filter_by_sport(all_props, 'MLB')
   return jsonify({
       'props': mlb_props,
       'count': len(mlb_props),
       'sport': 'MLB',
       'cached': bool(cached_props_data),
       'cache_age_minutes': (datetime.now() - cache_timestamp).total_seconds() / 60 if cache_timestamp else 0
   })

@app.route('/wnba-props')
def get_wnba_props():
   """Get WNBA player props only"""
   all_props = get_cached_or_fresh_data()
   wnba_props = filter_by_sport(all_props, 'WNBA')
   return jsonify({
       'props': wnba_props,
       'count': len(wnba_props),
       'sport': 'WNBA',
       'cached': bool(cached_props_data),
       'cache_age_minutes': (datetime.now() - cache_timestamp).total_seconds() / 60 if cache_timestamp else 0
   })

@app.route('/nba-props')
def get_nba_props():
   """Get NBA player props only"""
   all_props = get_cached_or_fresh_data()
   nba_props = filter_by_sport(all_props, 'NBA')
   return jsonify({
       'props': nba_props,
       'count': len(nba_props),
       'sport': 'NBA',
       'cached': bool(cached_props_data),
       'cache_age_minutes': (datetime.now() - cache_timestamp).total_seconds() / 60 if cache_timestamp else 0
   })

@app.route('/nfl-props')
def get_nfl_props():
   """Get NFL player props only"""
   all_props = get_cached_or_fresh_data()
   nfl_props = filter_by_sport(all_props, 'NFL')
   return jsonify({
       'props': nfl_props,
       'count': len(nfl_props),
       'sport': 'NFL',
       'cached': bool(cached_props_data),
       'cache_age_minutes': (datetime.now() - cache_timestamp).total_seconds() / 60 if cache_timestamp else 0
   })

@app.route('/nhl-props')
def get_nhl_props():
   """Get NHL player props only"""
   all_props = get_cached_or_fresh_data()
   nhl_props = filter_by_sport(all_props, 'NHL')
   return jsonify({
       'props': nhl_props,
       'count': len(nhl_props),
       'sport': 'NHL',
       'cached': bool(cached_props_data),
       'cache_age_minutes': (datetime.now() - cache_timestamp).total_seconds() / 60 if cache_timestamp else 0
   })

@app.route('/ufc-props')
def get_ufc_props():
   """Get UFC player props only"""
   all_props = get_cached_or_fresh_data()
   ufc_props = filter_by_sport(all_props, 'UFC')
   return jsonify({
       'props': ufc_props,
       'count': len(ufc_props),
       'sport': 'UFC',
       'cached': bool(cached_props_data),
       'cache_age_minutes': (datetime.now() - cache_timestamp).total_seconds() / 60 if cache_timestamp else 0
   })

@app.route('/top-props-by-sport')
def get_top_props_by_sport_endpoint():
   """Get top 10 props per sport"""
   all_props = get_cached_or_fresh_data()
   top_props = get_top_props_by_sport(all_props, limit=10)
   return jsonify({
       'props_by_sport': top_props,
       'total_props': len(all_props),
       'sports_count': len(top_props),
       'cached': bool(cached_props_data),
       'cache_age_minutes': (datetime.now() - cache_timestamp).total_seconds() / 60 if cache_timestamp else 0
   })

@app.route('/test-props')
def test_props():
   """Test endpoint - show first 5 props"""
   props = get_cached_or_fresh_data()
   return jsonify({
       'first_5_props': props[:5],
       'total_props': len(props),
       'cached': bool(cached_props_data),
       'cache_age_minutes': (datetime.now() - cache_timestamp).total_seconds() / 60 if cache_timestamp else 0
   })

@app.route('/refresh-props-cache')
def refresh_props_cache():
   """Force refresh the props cache"""
   global cached_props_data, cache_timestamp
   print("Forcing props cache refresh...")
   cached_props_data = []
   cache_timestamp = None
   props = get_cached_or_fresh_data()
   return jsonify({
       'message': 'Props cache refreshed successfully',
       'total_props': len(props),
       'cache_timestamp': cache_timestamp.isoformat() if cache_timestamp else None
   })

@app.route('/props-summary')
def get_props_summary():
   """Get summary of all props by sport"""
   all_props = get_cached_or_fresh_data()
   
   # Group by sport
   sports_summary = {}
   for prop in all_props:
       sport = prop['sport']
       if sport not in sports_summary:
           sports_summary[sport] = {
               'count': 0,
               'sample_markets': set(),
               'date_ranges': set()
           }
       sports_summary[sport]['count'] += 1
       sports_summary[sport]['sample_markets'].add(prop['market'])
       sports_summary[sport]['date_ranges'].add(prop['scraped_date_range'])
   
   # Convert sets to lists for JSON serialization
   for sport in sports_summary:
       sports_summary[sport]['sample_markets'] = list(sports_summary[sport]['sample_markets'])[:10]  # Limit to 10 examples
       sports_summary[sport]['date_ranges'] = list(sports_summary[sport]['date_ranges'])
   
   return jsonify({
       'summary': {
           'total_props': len(all_props),
           'sports_count': len(sports_summary),
           'sports_breakdown': sports_summary,
           'cached': bool(cached_props_data)
       }
   })

@app.route('/converted-lines')
def get_converted_lines():
   """Get props with converted bet lines (1+ -> Over 0.5, etc.)"""
   all_props = get_cached_or_fresh_data()
   
   # Filter props that had conversions
   converted_props = [
       prop for prop in all_props 
       if prop['betslip_line'] != prop['converted_betslip_line']
   ]
   
   return jsonify({
       'converted_props': converted_props,
       'count': len(converted_props),
       'total_props': len(all_props),
       'conversion_rate': f"{len(converted_props)/len(all_props)*100:.1f}%" if all_props else "0%",
       'cached': bool(cached_props_data)
   })

if __name__ == '__main__':
   # Test the scraper
   print("Testing props scraper...")
   props = scrape_player_props()
   
   # Cache the data globally
   cached_props_data = props
   cache_timestamp = datetime.now()
   
   print(f"Found {len(props)} props")
   
   if props:
       print("\nFirst prop:")
       print(f"Event: {props[0]['event']}")
       print(f"Market: {props[0]['market']}")
       print(f"Original Line: {props[0]['betslip_line']}")
       print(f"Converted Line: {props[0]['converted_betslip_line']}")
       print(f"Odds: {props[0]['odds']}")
       print(f"Sport: {props[0]['sport']}")
       print(f"Date Range: {props[0]['scraped_date_range']}")
   
   # Show summary by sport
   print("\n" + "="*50)
   print("PROPS SUMMARY BY SPORT")
   print("="*50)
   
   sports_count = {}
   for prop in props:
       sport = prop['sport']
       sports_count[sport] = sports_count.get(sport, 0) + 1
   
   for sport, count in sports_count.items():
       print(f"{sport}: {count} props")
   
   # Show converted lines examples
   print("\n" + "="*50)
   print("CONVERTED LINES EXAMPLES")
   print("="*50)
   
   converted_examples = [
       prop for prop in props 
       if prop['betslip_line'] != prop['converted_betslip_line']
   ][:10]
   
   for prop in converted_examples:
       print(f"{prop['market']}: {prop['betslip_line']} -> {prop['converted_betslip_line']}")
   
   print(f"\nTotal conversions: {len([p for p in props if p['betslip_line'] != p['converted_betslip_line']])}")
   
   print("\n" + "="*50)
   print("Starting Flask server...")
   print(f"Data is cached for {CACHE_DURATION_MINUTES} minutes")
   print("Visit /refresh-props-cache to force new scraping")
   print("="*50)
   
   # Start Flask app
   port = int(os.environ.get('PORT', 5000))
   app.run(debug=False, host='0.0.0.0', port=port)
