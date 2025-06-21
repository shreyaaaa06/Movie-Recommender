import requests
from flask import Flask, render_template_string, request, jsonify
import json
import threading

app = Flask(__name__)

# Replace with your TMDB API key , this is just a random values
API_KEY = "b2d4d0dcae3d71261a4b0a9d6491"
BASE_URL = "https://api.themoviedb.org/3"

class MovieRecommender:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = BASE_URL
        self.cache = {} 
        
    def search_movie_by_name(self, movie_name, language="en"):
        cache_key = f"search_movie_{movie_name}_{language}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        """Search for movies by name"""
        url = f"{self.base_url}/search/movie"
        params = {
            'api_key': self.api_key,
            'query': movie_name,
            'language': language,
            'include_adult': False
        }
        
        response = requests.get(url, params=params)
        if response.status_code == 200:
            result = response.json()
            self.cache[cache_key] = result  # Cache the result
            return result
    
    def get_similar_movies(self, movie_id, target_language=None):
        """Get similar movies based on movie ID"""
        url = f"{self.base_url}/movie/{movie_id}/similar"
        params = {
            'api_key': self.api_key,
            'language': 'en-US',
            'page': 1
        }
    
        response = requests.get(url, params=params)
        if response.status_code == 200:
            return response.json()
        return None
    
    def discover_movies_by_genre_flexible(self, genre_ids, language="en"):
        """Discover movies by genre with fallback to popular movies if not enough found"""
        
        # Build API parameters
        params = {
            'api_key': self.api_key,
            'with_genres': genre_ids,
            'sort_by': 'popularity.desc',
            'include_adult': False,
            'page': 1
        }
        
        # Add language filter if specified
        if language and language != "":
            params['with_original_language'] = language
        
        # Make API call
        url = f"{self.base_url}/discover/movie"
        try:
            response = requests.get(url, params=params)
            
            if response.status_code == 200:
                data = response.json()
                return data
            else:
                print(f"API error: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            print(f"Exception in discover_movies_by_genre_flexible: {e}")
            return None

    def discover_movies_by_genre_with_fallback(self, genre_ids, language="en"):
        """Discover movies by genre with fallback strategy"""
        
        # First try exact match with language
        results = self.discover_movies_by_genre_flexible(genre_ids, language)
        
        if results and len(results.get('results', [])) >= 10:
            return results
        
        # If not enough results, try without language filter
        results_no_lang = self.discover_movies_by_genre_flexible(genre_ids, "")
        
        if results_no_lang and len(results_no_lang.get('results', [])) > 0:
            return results_no_lang
        
        # If still not enough, get popular movies from the first genre
        if ',' in str(genre_ids):
            first_genre = str(genre_ids).split(',')[0]
            fallback_results = self.discover_movies_by_genre_flexible(first_genre, "")
            return fallback_results or {'results': []}
        
        return {'results': []}

    def get_similar_by_genre(self, movie_id, target_language=None):
        """Get movies with exactly the same genres first, then similar movies to reach 20 total - Optimized hybrid version"""

        # Create cache key
        cache_key = f"similar_genre_{movie_id}_{target_language or 'all'}"

        # Check cache first
        if hasattr(self, 'cache') and cache_key in self.cache:
            return self.cache[cache_key]

        # Initialize cache if it doesn't exist
        if not hasattr(self, 'cache'):
            self.cache = {}

        # Get the movie details to extract genres (with caching)
        movie_details_key = f"details_{movie_id}"
        if movie_details_key in self.cache:
            movie_details = self.cache[movie_details_key]
        else:
            movie_details = self.get_movie_details(movie_id)
            if movie_details:
                self.cache[movie_details_key] = movie_details

        if not movie_details or not movie_details.get('genres'):
            print(f"No movie details or genres found for movie_id: {movie_id}")
            return None

        # Extract and sort genre IDs
        original_genre_ids = sorted([genre['id'] for genre in movie_details['genres']])
        genre_string = ','.join(str(gid) for gid in original_genre_ids)
        
        print(f"Original movie genres: {genre_string}")  # Debug

        # Use the corrected discover method
        discover_results = self.discover_movies_by_genre_with_fallback(genre_string, target_language)
        
        if not discover_results or not discover_results.get('results'):
            print("No results from discover API")
            return None

        exact_matches = []
        similar_matches = []

        # Process the results
        movies_to_check = [movie for movie in discover_results['results'] if movie['id'] != movie_id]
        
        for movie in movies_to_check[:30]:  # Limit API calls
            # Check cache for movie details first
            detail_key = f"details_{movie['id']}"
            if detail_key in self.cache:
                movie_detail = self.cache[detail_key]
            else:
                movie_detail = self.get_movie_details(movie['id'])
                if movie_detail:
                    self.cache[detail_key] = movie_detail
            
            if movie_detail and movie_detail.get('genres'):
                movie_genre_ids = sorted([g['id'] for g in movie_detail['genres']])
                
                if movie_genre_ids == original_genre_ids:
                    exact_matches.append(movie)
                else:
                    # Check for significant genre overlap (at least 50% of genres match)
                    overlap = len(set(movie_genre_ids) & set(original_genre_ids))
                    if overlap >= len(original_genre_ids) * 0.5:
                        similar_matches.append(movie)
            
            # Early exit if we have enough exact matches
            if len(exact_matches) >= 20:
                break

        # Combine results: exact matches first, then similar ones
        final_results = exact_matches + similar_matches

        # If still not enough, get more from TMDB's similar endpoint
        if len(final_results) < 20:
            similar_cache_key = f"tmdb_similar_{movie_id}_{target_language or 'all'}"
            
            if similar_cache_key in self.cache:
                similar_movies = self.cache[similar_cache_key]
            else:
                similar_movies = self.get_similar_movies(movie_id, target_language)
                if similar_movies:
                    self.cache[similar_cache_key] = similar_movies
            
            if similar_movies and similar_movies.get('results'):
                # Add unique movies from similar endpoint
                existing_ids = {movie['id'] for movie in final_results}
                existing_ids.add(movie_id)  # Exclude original movie
                
                for movie in similar_movies['results']:
                    if movie['id'] not in existing_ids:
                        final_results.append(movie)
                        if len(final_results) >= 20:
                            break

        # Prepare final response
        result = {
            'results': final_results[:20],
            'total_results': len(final_results[:20]),
            'total_pages': 1,
            'page': 1
        }

        # Cache the final result
        self.cache[cache_key] = result
        
        print(f"Final results count: {len(result['results'])}")  # Debug

        return result

    def get_movie_details(self, movie_id):
        """Get detailed information about a movie"""
        movie_url = f"{self.base_url}/movie/{movie_id}"
        movie_params = {
            'api_key': self.api_key,
            'language': 'en-US',
            'append_to_response': 'credits,videos'
        }
        
        try:
            response = requests.get(movie_url, params=movie_params)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Error getting movie details for {movie_id}: {response.status_code}")
                return None
        except Exception as e:
            print(f"Exception getting movie details for {movie_id}: {e}")
            return None

    def get_genres(self):
        """Get list of all genres"""
        url = f"{self.base_url}/genre/movie/list"
        params = {
            'api_key': self.api_key,
            'language': 'en-US'
        }

        try:
            print(f"Making request to: {url}")  # Debug
            print(f"With params: {params}")  # Debug
            response = requests.get(url, params=params)
            print(f"Response status: {response.status_code}")  # Debug
            print(f"Response text: {response.text[:200]}...")  # Debug first 200 chars
        
            if response.status_code == 200:
                data = response.json()
                print(f"JSON data: {data}")  # Debug
                return data.get('genres', [])
            else:
                print(f"API error: {response.text}")
                return []
        except Exception as e:
            print(f"Exception in get_genres: {e}")
            return []
    def search_person(self, person_name):
        """Search for a person (actor/director) by name"""
        url = f"{self.base_url}/search/person"
        params = {
            'api_key': self.api_key,
            'query': person_name,
            'include_adult': False
        }
    
        try:
            response = requests.get(url, params=params)
            print(f"Person search response status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                print(f"Person search results: {len(data.get('results', []))} found")
                return data
            else:
                print(f"Person search failed: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"Error in search_person: {e}")
            return None

    def get_movies_by_actor(self, person_id):
        """Get movies featuring a specific actor"""
        url = f"{self.base_url}/person/{person_id}/movie_credits"
        params = {
            'api_key': self.api_key,
            'language': 'en-US'
        }
    
        try:
            response = requests.get(url, params=params)
            print(f"Movie credits response status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                print(f"Movie credits found: {len(data.get('cast', []))} movies")
                return data
            else:
                print(f"Movie credits failed: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"Error in get_movies_by_actor: {e}")
            return None



# Initialize the recommender
recommender = MovieRecommender(API_KEY)

# Common CSS styles for all pages
COMMON_STYLES = """
    
        <style>
            body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background: linear-gradient(135deg, #1a1a1a 0%, #2d1b1b 100%); color: #ffffff; }
            .container { max-width: 1200px; margin: 0 auto; }
            .navbar { background: linear-gradient(135deg, #cc0000 0%, #660000 100%); padding: 15px; border-radius: 10px; margin-bottom: 20px; box-shadow: 0 4px 15px rgba(204, 0, 0, 0.3); }
            .navbar a { color: white; text-decoration: none; margin-right: 20px; font-weight: bold; transition: all 0.3s ease; }
            .navbar a:hover { text-decoration: underline; transform: translateY(-2px); }
            .navbar a.active { background-color: rgba(255,255,255,0.2); padding: 8px 15px; border-radius: 5px; box-shadow: 0 2px 8px rgba(0,0,0,0.3); }
            .search-box { background: linear-gradient(135deg, #2a2a2a 0%, #1f1f1f 100%); padding: 20px; border-radius: 10px; margin-bottom: 20px; border: 1px solid #cc0000; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }
            .movie-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 20px; }
            .movie-card { background: linear-gradient(135deg, #2a2a2a 0%, #1f1f1f 100%); border-radius: 10px; padding: 15px; box-shadow: 0 4px 15px rgba(0,0,0,0.7); cursor: pointer; transition: all 0.3s ease; border: 1px solid #444; }
            .movie-card:hover { transform: translateY(-8px); box-shadow: 0 8px 25px rgba(204, 0, 0, 0.4); border-color: #cc0000; }
            .movie-poster { width: 100%; height: 300px; object-fit: cover; border-radius: 5px; }
            .movie-title { font-weight: bold; margin: 10px 0 5px 0; color: #ffffff; }
            .movie-year { color: #cccccc; font-size: 14px; }
            .movie-rating { color: #ff6b35; font-weight: bold; }
            input, select, button { padding: 12px; margin: 5px; border: 1px solid #cc0000; border-radius: 5px; background-color: #2a2a2a; color: #ffffff; }
            input:focus, select:focus { outline: none; border-color: #ff4444; box-shadow: 0 0 8px rgba(204, 0, 0, 0.3); }
            button { background: linear-gradient(135deg, #cc0000 0%, #990000 100%); color: white; cursor: pointer; font-weight: bold; transition: all 0.3s ease; }
            button:hover { background: linear-gradient(135deg, #ff0000 0%, #cc0000 100%); transform: translateY(-2px); box-shadow: 0 4px 15px rgba(204, 0, 0, 0.4); }
            .modal { display: none; position: fixed; z-index: 1000; left: 0; top: 0; width: 100%; height: 100%; background-color: rgba(0,0,0,0.8); }
            .modal-content { background: linear-gradient(135deg, #2a2a2a 0%, #1f1f1f 100%); margin: 5% auto; padding: 20px; border-radius: 10px; width: 80%; max-width: 800px; max-height: 80%; overflow-y: auto; border: 1px solid #cc0000; box-shadow: 0 8px 25px rgba(0,0,0,0.9); }
            .close { color: #cc0000; float: right; font-size: 28px; font-weight: bold; cursor: pointer; transition: color 0.3s ease; }
            .close:hover { color: #ff4444; }
            .movie-detail-poster { width: 200px; height: 300px; object-fit: cover; float: left; margin-right: 20px; border-radius: 10px; }
            .movie-details { overflow: hidden; color: #ffffff; }
            .genre-tag { background: linear-gradient(135deg, #cc0000 0%, #990000 100%); color: white; padding: 5px 10px; margin: 5px; border-radius: 15px; display: inline-block; font-size: 12px; }
            .cast-member { display: inline-block; margin: 5px; padding: 5px 10px; background-color: #333333; border-radius: 5px; color: #ffffff; border: 1px solid #555; }
            .page-header { background: linear-gradient(135deg, #2a2a2a 0%, #1f1f1f 100%); padding: 20px; border-radius: 10px; margin-bottom: 20px; text-align: center; border: 1px solid #cc0000; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }
            .search-result-header { background: linear-gradient(135deg, #330000 0%, #1a0000 100%); padding: 15px; border-radius: 10px; margin-bottom: 20px; border: 1px solid #cc0000; }
            .page-header h1, .search-result-header h3 { color: #ffffff; }
            .page-header p, .search-result-header p { color: #cccccc; }
            small { color: #cccccc; }
            .search-suggestions {
                position: absolute;
                background: #2a2a2a;
                border: 1px solid #cc0000;
                border-radius: 5px;
                max-height: 200px;
                overflow-y: auto;
                z-index: 1000;
                width: 100%;
                margin-top: 2px;
            }
            .suggestion-item {
                padding: 10px;
                cursor: pointer;
                border-bottom: 1px solid #444;
                color: white;
            }
            .suggestion-item:hover {
                background: #cc0000;
            }
            .suggestion-item:last-child {
                border-bottom: none;
            }
            
            #loader {
                border: 8px solid #f3f3f3;
                border-top: 8px solid #3498db;
                border-radius: 50%;
                width: 60px;
                height: 60px;
                animation: spin 1s linear infinite;
                position: fixed;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
                z-index: 1000;
            }

            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
        

        </style>

    """

# HOME PAGE - Search by Movie Name (FIXED VERSION)
HOME_PAGE = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Movie Recommender - Find Similar Movies</title>
    {COMMON_STYLES}
</head>
<body>
    <div class="container">
        <div class="navbar">
            <a href="/" class="active">🎬 Similar Movies</a>
            <a href="/browse">🌍 Browse by Genre</a>
            <a href="/actors">🎭 Movies by Actor</a>
        </div>
        
        <div class="page-header">
            <h1>🎬 Find Similar Movies</h1>
            <p>Enter a movie name and discover movies just like it!</p>
        </div>
        
        <div class="search-box">
            <h3>Search for Similar Movies</h3>
            <div>
                <input type="text" id="movieName" placeholder="Enter movie name (e.g., Avengers, Titanic)" style="width: 300px;">
                <select id="language">
                    <option value="en">English</option>
                    <option value="hi">Hindi</option>
                    <option value="es">Spanish</option>
                    <option value="fr">French</option>
                    <option value="de">German</option>
                    <option value="ja">Japanese</option>
                    <option value="ko">Korean</option>
                    <option value="zh">Chinese</option>
                    <option value="bn">Bengali</option>
                    
                </select>
                <button onclick="searchSimilarMovies()">Find Similar Movies</button>
            </div>
            <p><small>💡 Tip: Type a movie you love and we'll find movies with similar themes, genres, and style!</small></p>
        </div>
        
        <div id="results">
            <div style="text-align: center; padding: 50px; color: #666;">
                <h3>🔍 Enter a movie name above to discover similar movies!</h3>
                <p>Examples: "Iron Man", "The Dark Knight", "Titanic", "3 Idiots"</p>
            </div>
        </div>
    </div>

    <!-- Movie Details Modal -->
    <div id="movieModal" class="modal">
        <div class="modal-content">
            <span class="close" onclick="closeModal()">&times;</span>
            <div id="movieDetails"></div>
        </div>
    </div>

    <script>
        function searchSimilarMovies() {{
            const movieName = document.getElementById('movieName').value.trim();
            const language = document.getElementById('language').value;
            
            if (!movieName) {{
                alert('Please enter a movie name');
                return;
            }}
            
            // Show loading
            document.getElementById('results').innerHTML = '<div style="text-align: center; padding: 50px;"><h3>🔍 Searching for similar movies...</h3></div>';
            
            fetch(`/search_similar?movie_name=${{encodeURIComponent(movieName)}}&language=${{language}}`)
                .then(response => response.json())
                .then(data => displaySimilarResults(data, movieName))
                .catch(error => {{
                    console.error('Error:', error);
                    document.getElementById('results').innerHTML = '<div style="text-align: center; padding: 50px; color: red;"><h3>❌ Error occurred while searching. Please try again.</h3></div>';
                }});
        }}

        function displaySimilarResults(data, searchedMovie) {{
            const resultsDiv = document.getElementById('results');
            
            if (!data.results || data.results.length === 0) {{
                resultsDiv.innerHTML = `
                    <div style="text-align: center; padding: 50px; color: #666;">
                        <h3>😔 No similar movies found for "${{searchedMovie}}"</h3>
                        <p>Try searching for a more popular movie or check the spelling.</p>
                    </div>
                `;
                return;
            }}
            
            let html = `
                <div class="search-result-header">
                    <h3>🎯 Movies Similar to "${{searchedMovie}}"</h3>
                    <p>Found ${{data.results.length}} similar movies based on genre, themes, and style</p>
                </div>
                <div class="movie-grid">
            `;
            
            data.results.forEach(movie => {{
                const posterPath = movie.poster_path ? 
                    `https://image.tmdb.org/t/p/w300${{movie.poster_path}}` : 
                    'https://via.placeholder.com/300x450?text=No+Image';
                
                const releaseYear = movie.release_date ? new Date(movie.release_date).getFullYear() : 'Unknown';
                const rating = movie.vote_average ? movie.vote_average.toFixed(1) : 'N/A';
                
                html += `
                    <div class="movie-card" onclick="showMovieDetails(${{movie.id}})">
                        <img src="${{posterPath}}" alt="${{movie.title}}" class="movie-poster">
                        <div class="movie-title">${{movie.title}}</div>
                        <div class="movie-year">${{releaseYear}}</div>
                        <div class="movie-rating">⭐ ${{rating}}/10</div>
                    </div>
                `;
            }});
            
            html += '</div>';
            resultsDiv.innerHTML = html;
        }}

        // Movie details and modal functions
        function showMovieDetails(movieId) {{
            fetch(`/movie_details/${{movieId}}`)
                .then(response => response.json())
                .then(movie => {{
                    if (!movie || movie.error) {{
                        alert('Could not load movie details');
                        return;
                    }}
                    
                    const posterPath = movie.poster_path ? 
                        `https://image.tmdb.org/t/p/w300${{movie.poster_path}}` : 
                        'https://via.placeholder.com/200x300?text=No+Image';
                    
                    const genres = movie.genres ? movie.genres.map(g => `<span class="genre-tag">${{g.name}}</span>`).join('') : '';
                    const cast = movie.credits && movie.credits.cast ? 
                        movie.credits.cast.slice(0, 10).map(actor => `<span class="cast-member">${{actor.name}}</span>`).join('') : 
                        'Cast information not available';
                    
                    const trailer = movie.videos && movie.videos.results ? 
                        movie.videos.results.find(v => v.type === 'Trailer' && v.site === 'YouTube') : null;
                    
                    const trailerHtml = trailer ? 
                        `<p><strong>Trailer:</strong> <a href="https://www.youtube.com/watch?v=${{trailer.key}}" target="_blank">Watch on YouTube</a></p>` : 
                        '<p><strong>Trailer:</strong> Not available</p>';
                    
                    const runtime = movie.runtime ? `${{movie.runtime}} minutes` : 'Unknown';
                    const releaseDate = movie.release_date || 'Unknown';
                    const rating = movie.vote_average ? movie.vote_average.toFixed(1) : 'N/A';
                    
                    document.getElementById('movieDetails').innerHTML = `
                        <img src="${{posterPath}}" alt="${{movie.title}}" class="movie-detail-poster">
                        <div class="movie-details">
                            <h2>${{movie.title}}</h2>
                            <p><strong>Overview:</strong> ${{movie.overview || 'No description available'}}</p>
                            <p><strong>Release Date:</strong> ${{releaseDate}}</p>
                            <p><strong>Runtime:</strong> ${{runtime}}</p>
                            <p><strong>Rating:</strong> ⭐ ${{rating}}/10</p>
                            <p><strong>Genres:</strong> ${{genres}}</p>
                            ${{trailerHtml}}
                            <p><strong>Cast:</strong></p>
                            <div>${{cast}}</div>
                        </div>
                    `;
                    
                    document.getElementById('movieModal').style.display = 'block';
                }})
                .catch(error => {{
                    console.error('Error:', error);
                    alert('Error loading movie details');
                }});
        }}

        function closeModal() {{
            document.getElementById('movieModal').style.display = 'none';
        }}
        
        window.onclick = function(event) {{
            const modal = document.getElementById('movieModal');
            if (event.target == modal) {{
                modal.style.display = 'none';
            }}
        }}

        // Allow Enter key to search
        document.getElementById('movieName').addEventListener('keypress', function(e) {{
            if (e.key === 'Enter') {{
                searchSimilarMovies();
            }}
        }});
        
        document.getElementById('movieName').addEventListener('input', function(e) {{
            const query = e.target.value;
            if (query.length >= 2) {{
                showSuggestions(query, 'movieName');
            }} else {{
                hideSuggestions();
            }}
        }});

        function showSuggestions(query, inputId) {{
            fetch(`/search_suggestions?query=${{encodeURIComponent(query)}}`)
                .then(response => response.json())
                .then(suggestions => {{
                    const input = document.getElementById(inputId);
                    let dropdown = document.getElementById('suggestions-dropdown');
            
                    if (!dropdown) {{
                        dropdown = document.createElement('div');
                        dropdown.id = 'suggestions-dropdown';
                        dropdown.className = 'search-suggestions';
                        dropdown.style.position = 'absolute';
                        dropdown.style.width = input.offsetWidth + 'px';
                        input.parentNode.appendChild(dropdown);
                    }}
            
                    dropdown.innerHTML = '';
                    suggestions.forEach(item => {{
                        const div = document.createElement('div');
                        div.className = 'suggestion-item';
                        div.innerHTML = `${{item.title}} ${{item.year ? '(' + item.year + ')' : ''}} <small>[${{item.type}}]</small>`;
                        div.onclick = () => {{
                            input.value = item.title;
                            hideSuggestions();
                        }};
                        dropdown.appendChild(div);
                    }});
            
                    dropdown.style.display = suggestions.length > 0 ? 'block' : 'none';
                }});
        }}

        function hideSuggestions() {{
            const dropdown = document.getElementById('suggestions-dropdown');
            if (dropdown) dropdown.style.display = 'none';
        }}

        // Hide suggestions when clicking outside
        document.addEventListener('click', function(e) {{
            if (!e.target.closest('.search-box')) {{
                hideSuggestions();
            }}
        }});
    </script>
</body>
</html>
"""
BROWSE_PAGE = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Movie Recommender - Browse by Genre</title>
    {COMMON_STYLES}
    <style>
        .genre-selection {{ margin: 20px 0; }}
        .genre-chips {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 15px 0; }}
        .genre-chip {{ 
            background: #333333; 
            color: white; 
            padding: 8px 15px; 
            border-radius: 20px; 
            cursor: pointer; 
            border: 2px solid #555;
            transition: all 0.3s ease;
            user-select: none;
        }}
        .genre-chip:hover {{ background: #444444; }}
        .genre-chip.selected {{ 
            background: linear-gradient(135deg, #cc0000 0%, #990000 100%); 
            border-color: #cc0000; 
            box-shadow: 0 2px 8px rgba(204, 0, 0, 0.3);
        }}
        .search-controls {{ display: flex; gap: 15px; align-items: center; flex-wrap: wrap; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="navbar">
            <a href="/">🎬 Similar Movies</a>
            <a href="/browse" class="active">🌍 Browse by Genre</a>
            <a href="/actors">🎭 Movies by Actor</a>
        </div>
        
        <div class="page-header">
            <h1>🌍 Browse Movies by Genre & Language</h1>
            <p>Select your preferred language and genres to discover amazing movies!</p>
        </div>
        
        <div class="search-box">
            <h3>Browse Movies</h3>
            
            <div class="search-controls">
                <select id="language" style="width: 200px;">
                    <option value="">Select Language</option>
                    <option value="en">English</option>
                    <option value="hi">Hindi</option>
                    <option value="es">Spanish</option>
                    <option value="fr">French</option>
                    <option value="de">German</option>
                    <option value="ja">Japanese</option>
                    <option value="ko">Korean</option>
                    <option value="zh">Chinese</option>
                    <option value="bn">Bengali</option>
                    <option value="kn">Kannada</option>
                    <option value="mr">Marathi</option>
                    <option value="te">Telugu</option>
                    <option value="ta">Tamil</option>
                </select>
                <button onclick="browseMovies()">Find Movies</button>
                <button onclick="clearSelection()" style="background: #666;">Clear All</button>
            </div>
            
            <div class="genre-selection">
                <h4>Select Genres (you can pick multiple):</h4>
                <div class="genre-chips" id="genreChips">
                    <!-- Genres will be loaded here -->
                </div>
                <p id="selectedGenres" style="margin-top: 10px; color: #cccccc;"></p>
            </div>
            
            <p><small>💡 Tip: Select language and one or more genres. Mix genres for unique combinations!</small></p>
        </div>
        
        <div id="results">
            <div style="text-align: center; padding: 50px; color: #666;">
                <h3>🎭 Select language and genres above to discover amazing movies!</h3>
                <p>Examples: Hindi + Action + Comedy, English + Horror + Thriller</p>
            </div>
        </div>
    </div>

    <!-- Movie Details Modal -->
    <div id="movieModal" class="modal">
        <div class="modal-content">
            <span class="close" onclick="closeModal()">&times;</span>
            <div id="movieDetails"></div>
        </div>
    </div>

    <script>
        let selectedGenres = [];
        let allGenres = [];

        // Load genres when page loads
        window.onload = function() {{
            loadGenres();
        }};

        function loadGenres() {{
            console.log('Loading genres...');
            fetch('/get_genres')
                .then(response => {{
                    console.log('Genre response status:', response.status);
                    return response.json();
                }})
                .then(genres => {{
                    console.log('Genres received:', genres);
                    allGenres = genres;
                    const container = document.getElementById('genreChips');
                    container.innerHTML = '';
            
                    if (!genres || genres.length === 0) {{
                        container.innerHTML = '<p style="color: #cc0000;">Failed to load genres. Please refresh the page.</p>';
                        return;
                    }}
            
                    genres.forEach(genre => {{
                        const chip = document.createElement('div');
                        chip.className = 'genre-chip';
                        chip.textContent = genre.name;
                        chip.dataset.genreId = genre.id;
                        chip.onclick = () => toggleGenre(genre.id, genre.name, chip);
                        container.appendChild(chip);
                    }});
                }})
                .catch(error => {{
                    console.error('Error loading genres:', error);
                    document.getElementById('genreChips').innerHTML = '<p style="color: #cc0000;">Error loading genres. Please refresh the page.</p>';
                }});
        }}

        function toggleGenre(genreId, genreName, element) {{
            const index = selectedGenres.findIndex(g => g.id === genreId);
            
            if (index > -1) {{
                // Remove genre
                selectedGenres.splice(index, 1);
                element.classList.remove('selected');
            }} else {{
                // Add genre
                selectedGenres.push({{ id: genreId, name: genreName }});
                element.classList.add('selected');
            }}
            
            updateSelectedGenresDisplay();
        }}

        function updateSelectedGenresDisplay() {{
            const display = document.getElementById('selectedGenres');
            if (selectedGenres.length > 0) {{
                const names = selectedGenres.map(g => g.name).join(', ');
                display.textContent = `Selected: ${{names}}`;
                display.style.color = '#cc0000';
            }} else {{
                display.textContent = '';
            }}
        }}

        function clearSelection() {{
            selectedGenres = [];
            document.querySelectorAll('.genre-chip').forEach(chip => {{
                chip.classList.remove('selected');
            }});
            updateSelectedGenresDisplay();
            document.getElementById('results').innerHTML = `
                <div style="text-align: center; padding: 50px; color: #666;">
                    <h3>🎭 Select language and genres above to discover amazing movies!</h3>
                    <p>Examples: Hindi + Action + Comedy, English + Horror + Thriller</p>
                </div>
            `;
        }}

        function browseMovies() {{
            const language = document.getElementById('language').value;
            
            if (!language) {{
                alert('Please select a language');
                return;
            }}
            
            if (selectedGenres.length === 0) {{
                alert('Please select at least one genre');
                return;
            }}
            
            // Show loading
            document.getElementById('results').innerHTML = '<div style="text-align: center; padding: 50px;"><h3>🔍 Finding movies for you...</h3></div>';
            
            const languageNames = {{
                'en': 'English', 'hi': 'Hindi', 'es': 'Spanish', 'fr': 'French',
                'de': 'German', 'ja': 'Japanese', 'ko': 'Korean', 'zh': 'Chinese',
                'bn': 'Bengali', 'kn': 'Kannada', 'mr': 'Marathi', 'te': 'Telugu', 'ta': 'Tamil'
            }};
            
            const selectedLanguage = languageNames[language] || language;
            const genreIds = selectedGenres.map(g => g.id).join(',');
            const genreNames = selectedGenres.map(g => g.name).join(', ');
            
            fetch(`/browse_movies?language=${{language}}&genres=${{genreIds}}`)
                .then(response => response.json())
                .then(data => displayBrowseResults(data, selectedLanguage, genreNames))
                .catch(error => {{
                    console.error('Error:', error);
                    document.getElementById('results').innerHTML = '<div style="text-align: center; padding: 50px; color: red;"><h3>❌ Error occurred while browsing. Please try again.</h3></div>';
                }});
        }}

        function displayBrowseResults(data, language, genres) {{
            const resultsDiv = document.getElementById('results');
            
            if (!data.results || data.results.length === 0) {{
                resultsDiv.innerHTML = `
                    <div style="text-align: center; padding: 50px; color: #666;">
                        <h3>😔 No movies found for ${{language}} movies with genres: ${{genres}}</h3>
                        <p>Try selecting different genres or language combination.</p>
                    </div>
                `;
                return;
            }}
            
            let html = `
                <div class="search-result-header">
                    <h3>🎯 ${{language}} Movies: ${{genres}}</h3>
                    <p>Found ${{data.results.length}} movies matching your selection</p>
                </div>
                <div class="movie-grid">
            `;
            
            data.results.forEach(movie => {{
                const posterPath = movie.poster_path ? 
                    `https://image.tmdb.org/t/p/w300${{movie.poster_path}}` : 
                    'https://via.placeholder.com/300x450?text=No+Image';
                
                const releaseYear = movie.release_date ? new Date(movie.release_date).getFullYear() : 'Unknown';
                const rating = movie.vote_average ? movie.vote_average.toFixed(1) : 'N/A';
                
                html += `
                    <div class="movie-card" onclick="showMovieDetails(${{movie.id}})">
                        <img src="${{posterPath}}" alt="${{movie.title}}" class="movie-poster">
                        <div class="movie-title">${{movie.title}}</div>
                        <div class="movie-year">${{releaseYear}}</div>
                        <div class="movie-rating">⭐ ${{rating}}/10</div>
                    </div>
                `;
            }});
            
            html += '</div>';
            resultsDiv.innerHTML = html;
        }}

        // Movie details and modal functions
        function showMovieDetails(movieId) {{
            fetch(`/movie_details/${{movieId}}`)
                .then(response => response.json())
                .then(movie => {{
                    if (!movie || movie.error) {{
                        alert('Could not load movie details');
                        return;
                    }}
                    
                    const posterPath = movie.poster_path ? 
                        `https://image.tmdb.org/t/p/w300${{movie.poster_path}}` : 
                        'https://via.placeholder.com/200x300?text=No+Image';
                    
                    const genres = movie.genres ? movie.genres.map(g => `<span class="genre-tag">${{g.name}}</span>`).join('') : '';
                    const cast = movie.credits && movie.credits.cast ? 
                        movie.credits.cast.slice(0, 10).map(actor => `<span class="cast-member">${{actor.name}}</span>`).join('') : 
                        'Cast information not available';
                    
                    const trailer = movie.videos && movie.videos.results ? 
                        movie.videos.results.find(v => v.type === 'Trailer' && v.site === 'YouTube') : null;
                    
                    const trailerHtml = trailer ? 
                        `<p><strong>Trailer:</strong> <a href="https://www.youtube.com/watch?v=${{trailer.key}}" target="_blank">Watch on YouTube</a></p>` : 
                        '<p><strong>Trailer:</strong> Not available</p>';
                    
                    const runtime = movie.runtime ? `${{movie.runtime}} minutes` : 'Unknown';
                    const releaseDate = movie.release_date || 'Unknown';
                    const rating = movie.vote_average ? movie.vote_average.toFixed(1) : 'N/A';
                    
                    document.getElementById('movieDetails').innerHTML = `
                        <img src="${{posterPath}}" alt="${{movie.title}}" class="movie-detail-poster">
                        <div class="movie-details">
                            <h2>${{movie.title}}</h2>
                            <p><strong>Overview:</strong> ${{movie.overview || 'No description available'}}</p>
                            <p><strong>Release Date:</strong> ${{releaseDate}}</p>
                            <p><strong>Runtime:</strong> ${{runtime}}</p>
                            <p><strong>Rating:</strong> ⭐ ${{rating}}/10</p>
                            <p><strong>Genres:</strong> ${{genres}}</p>
                            ${{trailerHtml}}
                            <p><strong>Cast:</strong></p>
                            <div>${{cast}}</div>
                        </div>
                    `;
                    
                    document.getElementById('movieModal').style.display = 'block';
                }})
                .catch(error => {{
                    console.error('Error:', error);
                    alert('Error loading movie details');
                }});
        }}

        function closeModal() {{
            document.getElementById('movieModal').style.display = 'none';
        }}
        
        window.onclick = function(event) {{
            const modal = document.getElementById('movieModal');
            if (event.target == modal) {{
                modal.style.display = 'none';
            }}
        }}
    </script>
</body>
</html>
"""
ACTORS_PAGE = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Movie Recommender - Find Movies by Actor</title>
    {COMMON_STYLES}
</head>
<body>
    <div class="container">
        <div class="navbar">
            <a href="/">🎬 Similar Movies</a>
            <a href="/browse">🌍 Browse by Genre</a>
            <a href="/actors" class="active">🎭 Movies by Actor</a>
        </div>
        
        <div class="page-header">
            <h1>🎭 Find Movies by Actor</h1>
            <p>Enter an actor's name to discover all their movies!</p>
        </div>
        
        <div class="search-box">
            <h3>Search Movies by Actor</h3>
            <div style="position: relative;">
                <input type="text" id="actorName" placeholder="Enter actor name (e.g., Tom Hanks, Scarlett Johansson)" style="width: 400px;">
                <button onclick="searchMoviesByActor()">Find Movies</button>
            </div>
            <p><small>💡 Tip: Enter the full name of any actor to see their complete filmography!</small></p>
        </div>
        
        <div id="results">
            <div style="text-align: center; padding: 50px; color: #666;">
                <h3>🎭 Enter an actor's name above to discover their movies!</h3>
                <p>Examples: "Robert Downey Jr", "Meryl Streep", "Leonardo DiCaprio"</p>
            </div>
        </div>
    </div>

    <!-- Movie Details Modal -->
    <div id="movieModal" class="modal">
        <div class="modal-content">
            <span class="close" onclick="closeModal()">&times;</span>
            <div id="movieDetails"></div>
        </div>
    </div>

    <script>
        function searchMoviesByActor() {{
            const actorName = document.getElementById('actorName').value.trim();
            
            if (!actorName) {{
                alert('Please enter an actor name');
                return;
            }}
            
            // Show loading
            document.getElementById('results').innerHTML = '<div style="text-align: center; padding: 50px;"><h3>🔍 Searching for movies...</h3></div>';
            
            fetch(`/search_actor?actor_name=${{encodeURIComponent(actorName)}}`)
                .then(response => response.json())
                .then(data => displayActorResults(data))
                .catch(error => {{
                    console.error('Error:', error);
                    document.getElementById('results').innerHTML = '<div style="text-align: center; padding: 50px; color: red;"><h3>❌ Error occurred while searching. Please try again.</h3></div>';
                }});
        }}

        function displayActorResults(data) {{
            const resultsDiv = document.getElementById('results');
            
            if (!data.results || data.results.length === 0) {{
                resultsDiv.innerHTML =` 
                    <div style="text-align: center; padding: 50px; color: #666;">
                        <h3>😔 No movies found for this actor</h3>
                        <p>Try checking the spelling or use a different actor name.</p>
                    </div>
                `;
                return;
            }}
            
            let html =`
                <div class="search-result-header">
                    <h3>🎬 Movies featuring ${{data.actor_name}}</h3>
                    <p>Found ${{data.results.length}} movies</p>
                </div>
                <div class="movie-grid">
            `;
            
            data.results.forEach(movie => {{
                const posterPath = movie.poster_path ? 
                    `https://image.tmdb.org/t/p/w300${{movie.poster_path}}` : 
                    'https://via.placeholder.com/300x450?text=No+Image';
                
                const releaseYear = movie.release_date ? new Date(movie.release_date).getFullYear() : 'Unknown';
                const rating = movie.vote_average ? movie.vote_average.toFixed(1) : 'N/A';
                const character = movie.character ? `as ${{movie.character}}` : '';
                
                html +=` 
                    <div class="movie-card" onclick="showMovieDetails(${{movie.id}})">
                        <img src="${{posterPath}}" alt="${{movie.title}}" class="movie-poster">
                        <div class="movie-title">${{movie.title}}</div>
                        <div class="movie-year">${{releaseYear}}</div>
                        <div class="movie-rating">⭐ ${{rating}}/10</div>
                        <div style="font-size: 12px; color: #ccc; margin-top: 5px;">${{character}}</div>
                    </div>
                `;
            }});
            
            html += '</div>';
            resultsDiv.innerHTML = html;
        }}

        // Movie details and modal functions
        function showMovieDetails(movieId) {{
            fetch(`/movie_details/${{movieId}}`)
                .then(response => response.json())
                .then(movie => {{
                    if (!movie || movie.error) {{
                        alert('Could not load movie details');
                        return;
                    }}
                    
                    const posterPath = movie.poster_path ? 
                        `https://image.tmdb.org/t/p/w300${{movie.poster_path}}` : 
                        'https://via.placeholder.com/200x300?text=No+Image';
                    
                    const genres = movie.genres ? movie.genres.map(g => `<span class="genre-tag">${{g.name}}</span>`).join('') : '';
                    const cast = movie.credits && movie.credits.cast ? 
                        movie.credits.cast.slice(0, 10).map(actor => `<span class="cast-member">${{actor.name}}</span>`).join('') : 
                        'Cast information not available';
                    
                    const trailer = movie.videos && movie.videos.results ? 
                        movie.videos.results.find(v => v.type === 'Trailer' && v.site === 'YouTube') : null;
                    
                    const trailerHtml = trailer ? 
                        `<p><strong>Trailer:</strong> <a href="https://www.youtube.com/watch?v=${{trailer.key}}" target="_blank">Watch on YouTube</a></p>` : 
                        '<p><strong>Trailer:</strong> Not available</p>';
                    
                    const runtime = movie.runtime ? `${{movie.runtime}} minutes `: 'Unknown';
                    const releaseDate = movie.release_date || 'Unknown';
                    const rating = movie.vote_average ? movie.vote_average.toFixed(1) : 'N/A';
                    
                    document.getElementById('movieDetails').innerHTML =` 
                        <img src="${{posterPath}}" alt="${{movie.title}}" class="movie-detail-poster">
                        <div class="movie-details">
                            <h2>${{movie.title}}</h2>
                            <p><strong>Overview:</strong> ${{movie.overview || 'No description available'}}</p>
                            <p><strong>Release Date:</strong> ${{releaseDate}}</p>
                            <p><strong>Runtime:</strong> ${{runtime}}</p>
                            <p><strong>Rating:</strong> ⭐ ${{rating}}/10</p>
                            <p><strong>Genres:</strong> ${{genres}}</p>
                            ${{trailerHtml}}
                            <p><strong>Cast:</strong></p>
                            <div>${{cast}}</div>
                        </div>
                    `;
                    
                    document.getElementById('movieModal').style.display = 'block';
                }})
                .catch(error => {{
                    console.error('Error:', error);
                    alert('Error loading movie details');
                }});
        }}

        function closeModal() {{
            document.getElementById('movieModal').style.display = 'none';
        }}
        
        window.onclick = function(event) {{
            const modal = document.getElementById('movieModal');
            if (event.target == modal) {{
                modal.style.display = 'none';
            }}
        }}

        // Search suggestions functionality
        let debounceTimeout;
document.getElementById('actorName').addEventListener('input', function(e) {{
    const query = e.target.value;
    clearTimeout(debounceTimeout);
    if (query.length >= 2) {{
        debounceTimeout = setTimeout(function() {{
            showSuggestions(query, 'actorName');
        }}, 400);  // 400ms delay
    }} else {{
        hideSuggestions();
    }}
}});

        function showSuggestions(query, inputId) {{
            fetch(`/search_suggestions?query=${{encodeURIComponent(query)}}`)
                .then(response => response.json())
                .then(suggestions => {{
                    const input = document.getElementById(inputId);
                    let dropdown = document.getElementById('suggestions-dropdown');
                    
                    if (!dropdown) {{
                        dropdown = document.createElement('div');
                        dropdown.id = 'suggestions-dropdown';
                        dropdown.className = 'search-suggestions';
                        dropdown.style.position = 'absolute';
                        dropdown.style.width = input.offsetWidth + 'px';
                        input.parentNode.appendChild(dropdown);
                    }}
                    
                    dropdown.innerHTML = '';
                    
                    // Filter suggestions to show only actors for this page
                    const actorSuggestions = suggestions.filter(item => item.type === 'actor');
                    
                    actorSuggestions.forEach(item => {{
                        const div = document.createElement('div');
                        div.className = 'suggestion-item';
                        div.innerHTML = `${{item.title}} <small>[${{item.type}}]</small>`;
                        div.onclick = () => {{
                            input.value = item.title;
                            hideSuggestions();
                        }};
                        dropdown.appendChild(div);
                    }});
                    
                    dropdown.style.display = actorSuggestions.length > 0 ? 'block' : 'none';
                }})
                .catch(error => {{
                    console.error('Error fetching suggestions:', error);
                }});
        }}

        function hideSuggestions() {{
            const dropdown = document.getElementById('suggestions-dropdown');
            if (dropdown) dropdown.style.display = 'none';
        }}

        // Hide suggestions when clicking outside
        document.addEventListener('click', function(e) {{
            if (!e.target.closest('.search-box')) {{
                hideSuggestions();
            }}
        }});

        // Allow Enter key to search
        document.getElementById('actorName').addEventListener('keypress', function(e) {{
            if (e.key === 'Enter') {{
                searchMoviesByActor();
            }}
        }});
    </script>
</body>
</html>
"""  
# Flask Routes
@app.route('/')
def home():
    """Home page - Search similar movies by name"""
    return render_template_string(HOME_PAGE)

@app.route('/browse')
def browse():
    """Browse page - Search by language and genre"""
    return render_template_string(BROWSE_PAGE)

@app.route('/get_genres')
def get_genres():
    """Get list of all genres for dropdown"""
    try:
        print("get_genres route called")  # Debug
        genres = recommender.get_genres()
        print(f"Genres returned from recommender: {genres}")  # Debug
        print(f"Number of genres: {len(genres) if genres else 0}")  # Debug
        return jsonify(genres or [])
    except Exception as e:
        print(f"Exception in get_genres route: {e}")
        return jsonify([])
@app.route('/search_similar')
def search_similar():
    """Search for movies similar to the given movie name"""
    movie_name = request.args.get('movie_name', '')
    language = request.args.get('language', 'en')
    
    try:
        if not movie_name:
            return jsonify({'results': [], 'error': 'Movie name is required'})
        
        # First, search for the movie
        search_results = recommender.search_movie_by_name(movie_name, language)
        
        if search_results and search_results['results']:
            first_movie_id = search_results['results'][0]['id']
            
            # Get similar movies (don't filter by language for similar movies)
            similar_movies = recommender.get_similar_by_genre(first_movie_id, language)
            
            if similar_movies and similar_movies['results']:
                return jsonify(similar_movies)
            else:
                return jsonify({'results': [], 'error': 'No similar movies found'})
        else:
            return jsonify({'results': [], 'error': 'Movie not found'})
            
    except Exception as e:
        print(f"Error in search_similar: {e}")
        return jsonify({'results': [], 'error': str(e)})
@app.route('/actors')
def actors_page():
    """Actor search page"""
    return render_template_string(ACTORS_PAGE)

@app.route('/search_actor')
def search_actor():
    """Search for movies by actor name - improved version"""
    actor_name = request.args.get('actor_name', '')
    
    try:
        if not actor_name:
            return jsonify({'results': [], 'error': 'Actor name is required'})
        
        # Search for the actor
        person_results = recommender.search_person(actor_name)
        
        if person_results and person_results['results']:
            # Find the most popular/relevant person
            best_match = None
            for person in person_results['results']:
                # Skip if person doesn't have profile path (likely not famous)
                if not person.get('profile_path'):
                    continue
                    
                # Prefer exact name matches
                if person['name'].lower() == actor_name.lower():
                    best_match = person
                    break
                    
                # Otherwise pick the most popular one
                if not best_match or person.get('popularity', 0) > best_match.get('popularity', 0):
                    best_match = person
            
            # Fallback to first result if no good match found
            if not best_match:
                best_match = person_results['results'][0]
            
            person_id = best_match['id']
            
            # Get movies for this actor
            movie_credits = recommender.get_movies_by_actor(person_id)
            
            if movie_credits and movie_credits['cast']:
                # Filter out movies with very low ratings or no ratings
                valid_movies = [
                    movie for movie in movie_credits['cast'] 
                    if movie.get('vote_average', 0) > 3.0 and movie.get('poster_path')
                ]
                
                # Sort by popularity and vote average
                movies = sorted(valid_movies, 
                              key=lambda x: (x.get('popularity', 0) * x.get('vote_average', 0)), 
                              reverse=True)
                
                return jsonify({
                    'results': movies[:20],  # Limit to top 20
                    'actor_name': best_match['name'],
                    'actor_id': person_id
                })
        
        return jsonify({'results': [], 'error': 'Actor not found'})
        
    except Exception as e:
        print(f"Error in search_actor: {e}")
        return jsonify({'results': [], 'error': str(e)})

@app.route('/browse_movies')
def browse_movies():
    """Browse movies by language and multiple genres"""
    language = request.args.get('language', '')
    genres = request.args.get('genres', '')  # Now accepts comma-separated genre IDs
    
    try:
        if not language or not genres:
            return jsonify({'results': [], 'error': 'Both language and genres are required'})
        
        results = recommender.discover_movies_by_genre_flexible(genres, language)
        return jsonify(results or {'results': []})
        
    except Exception as e:
        print(f"Error in browse_movies: {e}")
        return jsonify({'results': [], 'error': str(e)})
@app.route('/movie_details/<int:movie_id>')
def movie_details(movie_id):
    """Get detailed information about a specific movie"""
    try:
        details = recommender.get_movie_details(movie_id)
        return jsonify(details or {'error': 'Movie not found'})
    except Exception as e:
        print(f"Error getting movie details: {e}")
        return jsonify({'error': str(e)})


@app.route('/search_suggestions')
def search_suggestions():
    """Get search suggestions for movies and actors"""
    query = request.args.get('query', '')
    
    if len(query) < 2:  # Only search if 2+ characters
        return jsonify([])
    
    try:
        suggestions = []
        
        # Search movies
        movie_results = recommender.search_movie_by_name(query)
        if movie_results and movie_results['results']:
            filtered_movies = [movie for movie in movie_results['results'] if movie['title'].lower().startswith(query.lower())]
            for movie in filtered_movies[:5]:

                suggestions.append({
                    'title': movie['title'],
                    'type': 'movie',
                    'year': movie.get('release_date', '')[:4] if movie.get('release_date') else ''
                })
        
        # Search actors
        actor_results = recommender.search_person(query)
        if actor_results and actor_results['results']:
            filtered_actors = [actor for actor in actor_results['results'] if actor['name'].lower().startswith(query.lower())]
            for actor in actor_results['results'][:5]:  # Top 5 actors
                suggestions.append({
                    'title': actor['name'],
                    'type': 'actor'
                })
        
        return jsonify(suggestions[:10])  # Limit to 10 total suggestions
        
    except Exception as e:
        return jsonify([])


if __name__ == '__main__':
    print("🎬 Starting Multi-Page Movie Recommender...")
    print("⚠️  Don't forget to replace 'b2d4d0dcae3d71261a4b0a9d6aaec491' with your actual TMDB API key!")
    print("🌐 Open your browser and go to:")
    print("   📍 Home Page (Similar Movies): http://localhost:5000")
    print("   📍 Browse Page (Genre Search): http://localhost:5000/browse")
    app.run(debug=True, host='0.0.0.0', port=5000)