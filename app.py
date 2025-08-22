import streamlit as st
import json
import re
import google.generativeai as genai
import time
import PyPDF2
import docx
import io
from datetime import date

# ==============================================================================
# API-avaimen käsittely ja perusasetukset
# ==============================================================================
TEOLOGINEN_PERUSOHJE = """
TÄRKEÄ PERUSOHJE: Olet teologinen assistentti, jonka ainoa ja tärkein tehtävä on auttaa käyttäjää ymmärtämään annettua Raamatun tekstiä sen omassa kontekstissa ja Raamatun kokonaisilmoituksen valossa.
Noudata seuraavia sääntöjä ehdottomasti:
1. Pysy lähteessä: Perusta KAIKKI vastauksesi ja tulkintasi AINOASTAAN sinulle annettuihin KR33/38-raamatunjakeisiin ja käyttäjän antamaan lisämateriaaliin.
2. Vältä oppisuuntauksia: Vältä systemaattisesti nojaamasta mihinkään tiettyyn ihmisten luomaan teologiseen järjestelmään, kuten dispensationalismiin, ellei käyttäjä erikseen pyydä vertailemaan niitä.
3. Kokonaisilmoitus: Pyri aina tulkitsemaan yksittäisiä jakeita laajemman, koko Raamatun kattavan ilmoituksen valossa.
4. Ole neutraali: Esitä asiat selkeästi ja tasapuolisesti.
"""

st.markdown("""
<style>
.stMarkdown p, .stTextArea textarea, .stTextInput input, .stButton button { font-family: 'Times New Roman', Times, serif; }
.stMarkdown p, .stTextArea textarea { font-size: 11pt; }
</style>
""", unsafe_allow_html=True)

# --- ISTUNNON TILAN ALUSTUS ---
if 'step' not in st.session_state:
    st.session_state.step = 'input'
if 'password_correct' not in st.session_state:
    st.session_state.password_correct = False
if 'aineisto' not in st.session_state:
    st.session_state.aineisto = {}
if 'login_toast_shown' not in st.session_state:
    st.session_state.login_toast_shown = False
if 'missing_verses' not in st.session_state:
    st.session_state.missing_verses = None
if 'token_count' not in st.session_state:
    st.session_state.token_count = {'input': 0, 'output': 0, 'total': 0}
if 'daily_token_count' not in st.session_state:
    st.session_state.daily_token_count = {'input': 0, 'output': 0, 'total': 0}
if 'show_token_counter' not in st.session_state:
    st.session_state.show_token_counter = False

# ==============================================================================
# KANONISEN KIRJAJÄRJESTYKSEN LISÄYS
# ==============================================================================
@st.cache_data
def lataa_raamattu(tiedostonimi="bible.json"):
    try:
        with open(tiedostonimi, "r", encoding="utf-8") as f:
            bible_data = json.load(f)
    except FileNotFoundError:
        st.error(f"KRIITTINEN VIRHE: Tiedostoa '{tiedostonimi}' ei löytynyt.")
        st.stop()
    
    book_map, book_name_map, book_data_map = {}, {}, {}
    canonical_book_names = []
    
    # Järjestetään kirjat numeerisesti ID:n mukaan kanonisen järjestyksen luomiseksi
    sorted_book_ids = sorted(bible_data.get('book', {}).keys(), key=int)

    for book_id in sorted_book_ids:
        book_content = bible_data['book'][book_id]
        book_data_map[book_id] = book_content
        info = book_content.get('info', {})
        proper_name = info.get('name', f"Kirja {book_id}")
        
        book_name_map[book_id] = proper_name
        canonical_book_names.append(proper_name)
        
        names = [info.get('name', ''), info.get('shortname', '')] + info.get('abbr', [])
        for name in names:
            if name:
                key = name.lower().replace('.', '').replace(' ', '')
                if key:
                    book_map[key] = (book_id, book_content)

    sorted_book_map = dict(sorted(book_map.items(), key=lambda item: len(item[0]), reverse=True))
    return bible_data, sorted_book_map, book_name_map, book_data_map, canonical_book_names

LOG_FILE = "cost_log.json"

def lataa_paivittainen_laskuri():
    today_str = str(date.today())
    try:
        with open(LOG_FILE, "r") as f:
            log_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        log_data = {}

    if today_str in log_data:
        st.session_state.daily_token_count = log_data[today_str]
    else:
        st.session_state.daily_token_count = {'input': 0, 'output': 0, 'total': 0}
        log_data = {today_str: st.session_state.daily_token_count}
        with open(LOG_FILE, "w") as f:
            json.dump(log_data, f)

def tallenna_paivittainen_laskuri(new_input, new_output):
    today_str = str(date.today())
    st.session_state.daily_token_count['input'] += new_input
    st.session_state.daily_token_count['output'] += new_output
    st.session_state.daily_token_count['total'] += (new_input + new_output)
    try:
        with open(LOG_FILE, "r") as f:
            log_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        log_data = {}
    log_data[today_str] = st.session_state.daily_token_count
    with open(LOG_FILE, "w") as f:
        json.dump(log_data, f, indent=4)

def laske_kustannus_arvio(token_count, model_name):
    HINNASTO_USD = {
        'gemini-1.5-flash': {'input': 0.075, 'output': 0.30},
        'gemini-1.5-pro': {'input': 1.25, 'output': 5.00}
    }
    USD_TO_EUR = 0.93
    if model_name not in HINNASTO_USD: return "Tuntematon malli"
    hinnat = HINNASTO_USD[model_name]
    input_cost_usd = (token_count['input'] / 1_000_000) * hinnat['input']
    output_cost_usd = (token_count['output'] / 1_000_000) * hinnat['output']
    total_cost_eur = (input_cost_usd + output_cost_usd) * USD_TO_EUR
    return f"~{total_cost_eur:.4f} €"

def etsi_viittaukset_tekstista(text, book_map, book_data_map):
    all_references = []
    pattern = re.compile(r'((?:\d\.\s*)?[A-Za-zäöÄÖ\s]+?)\s+(\d+)(?::([\d\s,-]+))?', re.IGNORECASE)
    matches = pattern.findall(text)

    for match in matches:
        book_candidate, chapter_str, verses_str = match
        book_candidate_clean = book_candidate.strip().lower().replace('.', '').replace(' ', '')
        
        found_key = None
        for key in book_map.keys():
            if book_candidate_clean.endswith(key):
                found_key = key
                break
        
        if found_key:
            book_id, content = book_map[found_key]
            book_proper_name = content['info'].get('name', book_candidate.strip())
            
            if verses_str:
                verse_parts = verses_str.split(',')
                for verse_part in verse_parts:
                    verse_part = verse_part.strip()
                    if not verse_part: continue
                    start_verse, end_verse = 0, 0
                    if '-' in verse_part:
                        try: start_verse, end_verse = map(int, verse_part.split('-'))
                        except ValueError: continue
                    else:
                        try: start_verse = end_verse = int(verse_part)
                        except ValueError: continue
                    
                    all_references.append({"book_id": book_id, "book_name": book_proper_name, "chapter": int(chapter_str), "start_verse": start_verse, "end_verse": end_verse, "original_match": f"{book_proper_name} {chapter_str}:{start_verse}" + (f"-{end_verse}" if start_verse != end_verse else "")})
            else:
                try:
                    last_verse_num = len(book_data_map[book_id]['chapter'][chapter_str]['verse'])
                    all_references.append({"book_id": book_id, "book_name": book_proper_name, "chapter": int(chapter_str), "start_verse": 1, "end_verse": last_verse_num, "original_match": f"{book_proper_name} {chapter_str}"})
                except KeyError: continue
    return all_references


def hae_tarkka_viittaus(ref, book_data_map, book_name_map, ennen, jalkeen):
    found_verses = set()
    book_id = ref["book_id"]
    chapter_str = str(ref["chapter"])
    book_proper_name = book_name_map.get(book_id, ref["book_name"])
    try:
        chapter_data = book_data_map[book_id]['chapter'][chapter_str]['verse']
        for verse_num in range(ref["start_verse"], ref["end_verse"] + 1):
                for i in range(verse_num - ennen, verse_num + jalkeen + 1):
                    verse_str = str(i)
                    if verse_str in chapter_data:
                        verse_text = chapter_data[verse_str]['text']
                        found_verses.add(f"{book_proper_name} {chapter_str}:{verse_str} - {verse_text}")
    except KeyError:
        return []
    return list(found_verses)

def lue_ladattu_tiedosto(uploaded_file):
    if uploaded_file is None: return ""
    try:
        file_extension = uploaded_file.name.split('.')[-1].lower()
        file_bytes = io.BytesIO(uploaded_file.getvalue())
        if file_extension == 'pdf':
            pdf_reader = PyPDF2.PdfReader(file_bytes)
            return "".join(page.extract_text() + "\n" for page in pdf_reader.pages)
        elif file_extension == 'docx':
            doc = docx.Document(file_bytes)
            return "\n".join([para.text for para in doc.paragraphs])
        elif file_extension == 'txt':
            try: return file_bytes.read().decode("utf-8")
            except UnicodeDecodeError:
                file_bytes.seek(0)
                return file_bytes.read().decode("latin-1")
    except Exception as e:
        st.error(f"Virhe tiedoston '{uploaded_file.name}' lukemisessa: {e}")
        return ""
    return ""

def etsi_ja_laajenna(bible_data, book_map, book_name_map, book_data_map, sana, kirja, ennen, jalkeen):
    siemen_jakeet, sana_lower = [], sana.lower().replace('*', '.*')
    try: pattern = re.compile(sana_lower)
    except re.error: return []
    
    key_to_find = None
    # Etsitään kirjan avain ensisijaisesti täsmällisellä, virallisella nimellä
    for k, v in book_name_map.items():
        if v.lower() == kirja.lower():
            # Etsi tämän book_id:n (k) vastaava avain book_mapista
            for map_key, (map_id, _) in book_map.items():
                if map_id == k:
                    key_to_find = map_key
                    break
            break

    if not key_to_find: return []

    book_id_str, book_content = book_map[key_to_find]
    oikea_nimi = book_name_map.get(book_id_str, f"Kirja {book_id_str}")
    
    for luku_str, luku_data in book_content.get('chapter', {}).items():
        for jae_str, jae_data in luku_data.get('verse', {}).items():
            if pattern.search(jae_data.get('text', '').lower()):
                siemen_jakeet.append((book_id_str, int(luku_str), int(jae_str)))

    laajennetut_jakeet = set()
    for book_id, luku, jae_nro in siemen_jakeet:
        for i in range(jae_nro - ennen, jae_nro + jalkeen + 1):
            try:
                jae_teksti = book_data_map[book_id]['chapter'][str(luku)]['verse'][str(i)]['text']
                laajennetut_jakeet.add(f"{oikea_nimi} {luku}:{i} - {jae_teksti}")
            except KeyError:
                continue
    return list(laajennetut_jakeet)

def tee_api_kutsu(prompt, malli, noudata_perusohjetta=True):
    final_prompt = f"{TEOLOGINEN_PERUSOHJE}\n\n---\n\nKÄYTTÄJÄN PYYNTÖ:\n{prompt}" if noudata_perusohjetta else prompt
    try:
        model = genai.GenerativeModel(malli)
        response = model.generate_content(final_prompt)
        
        if hasattr(response, 'usage_metadata'):
            usage = response.usage_metadata
            input_tokens = usage.prompt_token_count
            output_tokens = usage.candidates_token_count
            
            st.session_state.token_count['input'] += input_tokens
            st.session_state.token_count['output'] += output_tokens
            st.session_state.token_count['total'] += (input_tokens + output_tokens)
            
            tallenna_paivittainen_laskuri(input_tokens, output_tokens)
        
        time.sleep(1) 
        return response.text
    except Exception as e:
        st.error(f"API-VIRHE: {e}")
        return None

def luo_sisallysluettelo(aihe, malli, noudata_perusohjetta):
    prompt = f"Olet teologi. Luo yksityiskohtainen ja selkeä sisällysluettelo laajalle opetukselle aiheesta '{aihe}'. Rakenna looginen runko, jossa on pää- ja alakohtia. Vastaa AINOASTAAN numeroituna listana. KIELLETTYÄ: Älä KOSKAAN lisää esimerkkilainauksia tai Raamatun jakeita sulkuihin tai mihinkään muuallekaan sisällysluetteloon. Vastaus saa sisältää AINOASTAAN otsikoita ja numerointia."
    return tee_api_kutsu(prompt, malli, noudata_perusohjetta)

def jarjestele_jakeet_osioihin(sisallysluettelo, jakeet, malli, noudata_perusohjetta):
    jae_teksti = "\n".join(jakeet)
    prompt = f"Järjestele annetut Raamatun jakeet opetuksen sisällysluettelon mukaisiin osioihin. SISÄLLYSLUETTELO:\n{sisallysluettelo}\n\nLÖYDETYT JAKEET:\n{jae_teksti}\n\nVastaa AINOASTAAN JSON-muodossa, jossa avaimet ovat sisällysluettelon täsmällisiä otsikoita ja arvot ovat listoja kyseiseen osioon kuuluvista jakeista merkkijonoina. Älä muuta jakeiden muotoilua."
    vastaus_str = tee_api_kutsu(prompt, malli, noudata_perusohjetta)
    try:
        cleaned_response = vastaus_str.strip().replace("```json", "").replace("```", "")
        return json.loads(cleaned_response)
    except (json.JSONDecodeError, AttributeError):
        return None

def kirjoita_osio(aihe, osion_otsikko, jakeet, lisamateriaali, sanamaara_osio, malli, noudata_perusohjetta):
    jae_teksti = "\n".join(jakeet) if jakeet else "Ei Raamattu-jakeita tähän osioon."
    lisamateriaali_osio = f"\n\n--- KÄYTTÄJÄN ANTAMA LISÄMATERIAALI ---\n{lisamateriaali}" if lisamateriaali else ""
    prompt = f"Olet teologi. Kirjoita yksi kappale laajasta opetuksesta pääaiheella '{aihe}'. Tämän kappaleen tarkka otsikko on '{osion_otsikko}'. Perusta kirjoituksesi AINOASTAAN seuraaviin KR33/38-jakeisiin:\n\n--- RAAMATUN LÄHTEET ---\n{jae_teksti}{lisamateriaali_osio}\n\nKirjoita selkeä, johdonmukainen ja perusteltu teksti. Älä viittaa muihin kuin annettuihin jakeisiin. Pyri noin {sanamaara_osio} sanan pituuteen. Muotoile vastauksesi Markdown-muodossa."
    return tee_api_kutsu(prompt, malli, noudata_perusohjetta)

def check_password():
    st.header("🔑 Kirjaudu sisään")
    password = st.text_input("Syötä salasana", type="password")
    try:
        correct_password = st.secrets["APP_PASSWORD"]
        is_public_env = True
    except (KeyError, FileNotFoundError):
        is_public_env = False
    if is_public_env:
        if st.button("Kirjaudu"):
            if password == correct_password: 
                st.session_state.password_correct = True
                st.session_state.login_toast_shown = False
                st.rerun()
            else:
                st.error("Salasana on virheellinen.")
    else: 
        st.session_state.password_correct = True
        
# ==============================================================================
# NAVIGAATIOFUNKTIOIDEN LISÄYS
# ==============================================================================
def reset_session():
    st.session_state.step = 'input'
    st.session_state.aineisto = {}
    st.session_state.missing_verses = None
    st.session_state.token_count = {'input': 0, 'output': 0, 'total': 0}
    st.rerun()

# --- PÄÄOHJELMA ---
st.set_page_config(page_title="Älykäs Raamattu-tutkija", layout="wide")

if not st.session_state.password_correct:
    check_password()
else:
    st.title("📖 Älykäs Raamattu-tutkija v13.2")
    # Ladataan nyt myös kanoninen kirjalista
    bible_data, book_map, book_name_map, book_data_map, canonical_book_names = lataa_raamattu()
    lataa_paivittainen_laskuri()

    try:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    except (KeyError, FileNotFoundError):
        st.error("API-avainta ei löydy. Määritä se Streamlitin secret-hallinnassa (GEMINI_API_KEY).")
        st.stop()
    
    if not st.session_state.login_toast_shown:
        st.toast("Kirjautuminen onnistui!", icon="🎉")
        st.session_state.login_toast_shown = True
    
    if st.session_state.step == 'input':
        st.header("1. Syötä tutkimuksen aihe")
        with st.sidebar:
            st.header("Asetukset")
            st.subheader("Tekoälyn asetukset")
            malli_valinta_ui = st.selectbox("Valitse Gemini-malli:", ('gemini-1.5-flash', 'gemini-1.5-pro'), index=0, key="malli_input")
            noudata_perusohjetta_luodessa = st.checkbox("Noudata teologista perusohjetta", value=True, key="noudata_input")
            
            st.divider()
            st.session_state.show_token_counter = st.checkbox("Näytä kulutuslaskurit", value=st.session_state.get('show_token_counter', False))
            if st.session_state.show_token_counter:
                st.subheader("Session kulutus")
                session_hinta = laske_kustannus_arvio(st.session_state.token_count, malli_valinta_ui)
                st.metric(label="Tokenit", value=f"{st.session_state.token_count['total']:,}", help=f"Arvioidut kustannukset: {session_hinta}")

                st.subheader(f"Päivän kulutus")
                daily_hinta = laske_kustannus_arvio(st.session_state.daily_token_count, malli_valinta_ui)
                st.metric(label="Tokenit yhteensä", value=f"{st.session_state.daily_token_count['total']:,}", help=f"Arvioidut kustannukset: {daily_hinta}")
        
        aihe = st.text_area("Mikä on opetuksen tai tutkimuksen pääaihe?", "Mitä Johannes 3:16 meille opettaa?", height=150)
        ladatut_tiedostot = st.file_uploader("Lataa lisämateriaalia (valinnainen)", type=['txt', 'pdf', 'docx'], accept_multiple_files=True)
        
        if st.button("Luo tutkimussuunnitelma →", type="primary"):
            st.session_state.token_count = {'input': 0, 'output': 0, 'total': 0}
            with st.spinner("Analysoidaan aihetta ja luodaan tutkimussuunnitelmaa..."):
                st.session_state.aineisto = {
                    'aihe': aihe, 'malli': malli_valinta_ui, 'noudata_ohjetta': noudata_perusohjetta_luodessa
                }
                lisamateriaalit = [lue_ladattu_tiedosto(tiedosto) for tiedosto in ladatut_tiedostot] if ladatut_tiedostot else []
                st.session_state.aineisto['lisamateriaali'] = "\n\n---\n\n".join(lisamateriaalit)
                
                suunnitelma_prompt = f"Analysoi Raamatun opetusaihe: '{aihe}'. Luo JSON-muodossa lista avainsanoista ('hakusanat') ja Raamatun kirjoista ('kirjat'), joista aiheeseen liittyviä jakeita todennäköisimmin löytyy. Jos aihe on tarkka jae (kuten 'Joh. 3:16'), rajoita ehdotetut kirjat pääasiassa samaan kirjaan ja muutamaan tärkeimpään temaattiseen rinnakkaispaikkaan. Jos aihe on laaja (kuten 'Rakkaus'), ehdota kirjoja laajasti koko Raamatusta."
                suunnitelma_str = tee_api_kutsu(suunnitelma_prompt, 'gemini-1.5-flash', noudata_perusohjetta_luodessa)
                try:
                    cleaned_str = suunnitelma_str.strip().replace("```json", "").replace("```", "")
                    suunnitelma = json.loads(cleaned_str)
                except (json.JSONDecodeError, AttributeError):
                    st.warning("Tutkimussuunnitelman automaattinen luonti epäonnistui. Voit täyttää kentät manuaalisesti.")
                    suunnitelma = {"hakusanat": [], "kirjat": []}
                
                st.session_state.aineisto['hakusanat'] = suunnitelma.get("hakusanat", [])
                st.session_state.aineisto['kirjat'] = suunnitelma.get("kirjat", [])
                
                st.session_state.step = 'plan_review'
                st.rerun()

    elif st.session_state.step == 'plan_review':
        st.header("2. Määritä tutkimussuunnitelma")
        st.info("Tekoäly on ehdottanut seuraavia hakusanoja ja Raamatun kirjoja. Voit muokata niitä vapaasti ennen kuin aloitat varsinaisen jakeiden haun.")

        with st.sidebar:
            st.header("Navigaatio")
            if st.button("← Muokkaa aihetta"):
                st.session_state.step = 'input'
                st.rerun()
            if st.button("Lopeta ja aloita alusta"):
                reset_session()
            st.divider()
            st.header("Asetukset")
            st.subheader("Haun laajuus")
            jakeita_ennen = st.slider("Jakeita ennen osumaa:", 0, 10, 0)
            jakeita_jalkeen = st.slider("Jakeita osuman jälkeen:", 0, 10, 0)

        col1, col2 = st.columns(2)
        with col1:
            hakusanat_str = st.text_area("Hakusanat (yksi per rivi)", 
                                         value="\n".join(st.session_state.aineisto.get('hakusanat', [])), 
                                         height=300)
        with col2:
            # Käytetään nyt kanonista järjestystä
            kaikki_kirjat = canonical_book_names
            
            ai_suggested_books = st.session_state.aineisto.get('kirjat', [])
            default_books = []
            for book_suggestion in ai_suggested_books:
                key = book_suggestion.lower().replace('.', '').replace(' ', '')
                if key in book_map:
                    book_id, _ = book_map[key]
                    proper_name = book_name_map.get(book_id)
                    if proper_name and proper_name in kaikki_kirjat:
                        default_books.append(proper_name)

            valitut_kirjat = st.multiselect("Raamatun kirjat", 
                                            options=kaikki_kirjat, 
                                            default=default_books)

        if st.button("Aloita tutkimus →", type="primary"):
            with st.spinner("Kerätään aineistoa..."):
                st.session_state.aineisto['jakeita_ennen'] = jakeita_ennen
                st.session_state.aineisto['jakeita_jalkeen'] = jakeita_jalkeen
                final_hakusanat = [s.strip() for s in hakusanat_str.split('\n') if s.strip()]
                final_kirjat = valitut_kirjat
                
                kaikki_loydetyt_jakeet = set()
                
                st.write("Haetaan viittauksia aiheesta...")
                initial_refs = etsi_viittaukset_tekstista(st.session_state.aineisto['aihe'], book_map, book_data_map)
                kaikki_loydetyt_jakeet.update(v for ref in initial_refs for v in hae_tarkka_viittaus(ref, book_data_map, book_name_map, jakeita_ennen, jakeita_jalkeen))
                
                st.write("Haetaan jakeita tutkimussuunnitelman mukaan...")
                progress_bar = st.progress(0, text="Valmistellaan hakua...")
                total_searches = len(final_kirjat) * len(final_hakusanat)
                current_search = 0

                for kirja in final_kirjat:
                    for sana in final_hakusanat:
                        jakeet = etsi_ja_laajenna(bible_data, book_map, book_name_map, book_data_map, sana, kirja, jakeita_ennen, jakeita_jalkeen)
                        kaikki_loydetyt_jakeet.update(jakeet)
                        current_search += 1
                        if total_searches > 0:
                            progress_bar.progress(current_search / total_searches, text=f"Etsitään: '{sana}' ({kirja})")
                
                st.session_state.aineisto['jakeet'] = sorted(list(kaikki_loydetyt_jakeet))
                
                st.write("Luodaan sisällysluettelo...")
                sisallysluettelo_str = luo_sisallysluettelo(st.session_state.aineisto['aihe'], st.session_state.aineisto['malli'], st.session_state.aineisto['noudata_ohjetta'])
                st.session_state.aineisto['sisallysluettelo'] = sisallysluettelo_str
                
                st.session_state.step = 'review'
                st.rerun()

    elif st.session_state.step == 'review':
        st.header("3. Tarkista sisällysluettelo ja lähteet")

        with st.sidebar:
            st.header("Navigaatio")
            if st.button("← Muokkaa suunnitelmaa"):
                st.session_state.step = 'plan_review'
                st.rerun()
            if st.button("Lopeta ja aloita alusta"):
                reset_session()
            st.divider()
            st.header("Viimeistely")
            toimintatapa = st.radio("Valitse lopputuloksen tyyppi:", ("Valmis opetus (Optimoitu)", "Tutkimusraportti (Jatkojalostukseen)"), key="toimintatapa_valinta")
            sanamaara = st.number_input("Tavoitesanamäärä (vain opetukselle)", min_value=300, max_value=20000, value=4000, step=100, key="sanamaara_valinta")
            if st.button("Tarkista ja jatka →", type="primary"):
                st.session_state.aineisto['sisallysluettelo'] = st.session_state.sisallysluettelo_editori
                st.session_state.aineisto['toimintatapa'] = toimintatapa
                st.session_state.aineisto['sanamaara'] = sanamaara
                with st.spinner("Tarkistetaan viittauksia sisällysluettelosta..."):
                    references_in_toc = etsi_viittaukset_tekstista(st.session_state.sisallysluettelo_editori, book_map, book_data_map)
                    existing_verses_list_lower = [v.lower() for v in st.session_state.aineisto.get('jakeet', [])]
                    missing = [ref for ref in references_in_toc if not all(any(line.startswith(f'{ref["book_name"]} {ref["chapter"]}:{v_num}'.lower() + " -") for line in existing_verses_list_lower) for v_num in range(ref['start_verse'], ref['end_verse'] + 1))]
                if not missing:
                    st.session_state.missing_verses = None
                    st.session_state.step = 'output'
                else:
                    st.session_state.missing_verses = missing
                st.rerun()

        if st.session_state.missing_verses:
            st.warning("⚠️ **Huomio!** Seuraavia sisällysluettelossa mainittuja viittauksia ei löytynyt kerätystä aineistosta. Haluatko hakea ne ja lisätä aineistoon?")
            st.markdown("\n".join([f'- {ref["original_match"]}' for ref in st.session_state.missing_verses]))
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Kyllä, hae ja lisää puuttuvat jakeet", type="primary"):
                    with st.spinner("Noudetaan puuttuvia jakeita..."):
                        newly_fetched = set(st.session_state.aineisto.get('jakeet', []))
                        for ref in st.session_state.missing_verses:
                            fetched = hae_tarkka_viittaus(ref, book_data_map, book_name_map, st.session_state.aineisto['jakeita_ennen'], st.session_state.aineisto['jakeita_jalkeen'])
                            newly_fetched.update(fetched)
                        st.session_state.aineisto['jakeet'] = sorted(list(newly_fetched))
                    st.session_state.missing_verses = None
                    st.rerun()
            with col2:
                if st.button("Ei, jatka ilman näitä jakeita"):
                    st.session_state.missing_verses = None
                    st.rerun()
        else:
            st.text_area("Muokkaa sisällysluetteloa tarvittaessa:", value=st.session_state.aineisto.get('sisallysluettelo', ''), height=300, key='sisallysluettelo_editori')
            with st.expander(f"Näytä {len(st.session_state.aineisto.get('jakeet', []))} kerättyä jaetta"):
                st.text_area("Kerätty lähdemateriaali:", value="\n".join(st.session_state.aineisto.get('jakeet', [])), height=300, key="jakeet_naytto")

    elif st.session_state.step == 'output':
        st.header("4. Valmis tuotos")
        aineisto = st.session_state.aineisto
        lopputulos = ""

        with st.sidebar:
            st.header("Navigaatio")
            if st.button("← Muokkaa sisällysluetteloa"):
                st.session_state.step = 'review'
                st.rerun()
            if st.button("Lopeta ja aloita alusta"):
                reset_session()
            st.divider()
            if st.session_state.show_token_counter:
                # ... kulutuslaskurit ...
                pass
        
        with st.spinner("Järjestellään jakeita osioihin..."):
            jae_kartta = jarjestele_jakeet_osioihin(aineisto['sisallysluettelo'], aineisto['jakeet'], aineisto['malli'], aineisto['noudata_ohjetta'])
            aineisto['suodatettu_jaemaara'] = len({jae for jae_list in jae_kartta.values() for jae in jae_list}) if jae_kartta else 0

        if aineisto.get('toimintatapa') == "Valmis opetus (Optimoitu)":
            with st.status("Kirjoitetaan opetusta...", expanded=True) as status:
                sisallysluettelo_rivit = [rivi.strip() for rivi in aineisto['sisallysluettelo'].split('\n') if rivi.strip() and re.match(r'^\d', rivi)]
                koko_opetus, osioiden_maara = [], len(sisallysluettelo_rivit)
                sanamaara_per_osio = aineisto['sanamaara'] // osioiden_maara if osioiden_maara > 0 else aineisto['sanamaara']
                
                for i, otsikko in enumerate(sisallysluettelo_rivit):
                    status.write(f"Kirjoitetaan osiota {i+1}/{osioiden_maara}: {otsikko}...")
                    puhdas_otsikko = re.sub(r'^\d+(\.\d+)*\s*\.?\s*', '', otsikko)
                    relevantit_jakeet = jae_kartta.get(otsikko, []) if jae_kartta else aineisto['jakeet']
                    osio_teksti = kirjoita_osio(aineisto['aihe'], puhdas_otsikko, relevantit_jakeet, aineisto['lisamateriaali'], sanamaara_per_osio, aineisto['malli'], aineisto['noudata_ohjetta'])
                    if osio_teksti:
                        koko_opetus.append(f"### {otsikko}\n\n{osio_teksti}\n\n")
                
                status.update(label="Opetus on valmis!", state="complete", expanded=False)
                lopputulos = "".join(koko_opetus)

        elif aineisto.get('toimintatapa') == "Tutkimusraportti (Jatkojalostukseen)":
            with st.spinner("Kootaan tutkimusraportin pohjaa..."):
                komentopohja = f"""AIHE:\n{aineisto['aihe']}\n\n---\nSISÄLLYSLUETTELO, JOTA TULEE NOUDATTAA:\n{aineisto['sisallysluettelo']}\n\n---\nLÄHDEMATERIAALI (AINOAT SALLITUT KR33/38-JAKEET):\n{"\n".join(aineisto['jakeet'])}\n\n---\nLISÄMATERIAALI:\n{aineisto['lisamateriaali'] if aineisto['lisamateriaali'] else "Ei lisämateriaalia."}\n\n---\nTEHTÄVÄNANTO:\nKirjoita yllä olevien ohjeiden ja materiaalien pohjalta kattava opetus tai tutkimusraportti."""
                lopputulos = komentopohja

        alkuperainen_maara = len(aineisto.get('jakeet', []))
        suodatettu_maara = aineisto.get('suodatettu_jaemaara', 0)
        info_teksti = f"Jakeita (Kerätty / Käytetty): **{alkuperainen_maara} / {suodatettu_maara}**"
        if aineisto.get('toimintatapa') == "Valmis opetus (Optimoitu)" and lopputulos:
            sanojen_maara = len(re.findall(r'\w+', lopputulos))
            info_teksti = f"Sanamäärä: **~{sanojen_maara}** | " + info_teksti
        
        st.info(info_teksti)
        st.download_button("Lataa tiedostona (.txt)", data=lopputulos, file_name="lopputulos.txt")
        st.text_area("Lopputulos:", value=lopputulos, height=600)