import streamlit as st
import json
import re
import google.generativeai as genai
import time
import PyPDF2
import docx
import io

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
/* Estetään "Press Ctrl+Enter to apply" -teksti */
.stTextArea [data-testid="stMarkdownContainer"] p {
    display: none;
}
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


# --- TAUSTA-FUNKTIOT ---
@st.cache_data
def lataa_raamattu(tiedostonimi="bible.json"):
    try:
        with open(tiedostonimi, "r", encoding="utf-8") as f:
            bible_data = json.load(f)
    except FileNotFoundError:
        st.error(f"KRIITTINEN VIRHE: Tiedostoa '{tiedostonimi}' ei löytynyt.")
        st.stop()
    book_map, book_name_map, book_data_map = {}, {}, {}
    for book_id, book_content in bible_data.get('book', {}).items():
        book_data_map[book_id] = book_content
        info, target = book_content.get('info', {}), (book_id, book_content)
        proper_name = info.get('name', f"Kirja {book_id}")
        book_name_map[book_id] = proper_name
        names = [info.get('name', ''), info.get('shortname', '')] + info.get('abbr', [])
        for name in names:
            if name:
                key = name.lower().replace('.', '').replace(' ', '')
                if key: book_map[key] = target
    return bible_data, book_map, book_name_map, book_data_map

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
        else:
            st.warning(f"Tiedostomuotoa '.{file_extension}' ei tueta.")
            return ""
    except Exception as e:
        st.error(f"Virhe tiedoston '{uploaded_file.name}' lukemisessa: {e}")
        return ""

def etsi_ja_laajenna(bible_data, book_map, book_name_map, book_data_map, sana, kirja, ennen, jalkeen):
    siemen_jakeet, sana_lower = [], sana.lower().replace('*', '.*')
    try: pattern = re.compile(sana_lower)
    except re.error: return []
    key_to_find = kirja.lower().replace('.', '').replace(' ', '')
    if key_to_find not in book_map: return []
    
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
        time.sleep(1) 
        return response.text
    except Exception as e:
        st.error(f"API-VIRHE: {e}")
        return None

def luo_sisallysluettelo(aihe, malli, noudata_perusohjetta):
    prompt = f"Olet teologi. Luo yksityiskohtainen sisällysluettelo laajalle opetukselle aiheesta '{aihe}'. Rakenna runko, jossa on johdanto, 3-5 pääkohtaa ja jokaiseen 2-4 alakohtaa, sekä yhteenveto. Vastaa AINOASTAAN numeroituna listana."
    return tee_api_kutsu(prompt, malli, noudata_perusohjetta)

def jarjestele_jakeet_osioihin(sisallysluettelo, jakeet, malli, noudata_perusohjetta):
    jae_teksti = "\n".join(jakeet)
    prompt = f"Järjestele annetut Raamatun jakeet opetuksen sisällysluettelon mukaisiin osioihin. SISÄLLYSLUETTELO:\n{sisallysluettelo}\n\nLÖYDETYT JAKEET:\n{jae_teksti}\n\nVastaa AINOASTAAN JSON-muodossa. Avaimena on sisällysluettelon TÄSMÄLLINEN otsikko ja arvona lista siihen sopivista jakeista."
    vastaus_str = tee_api_kutsu(prompt, malli, noudata_perusohjetta)
    try:
        cleaned_response = vastaus_str.strip().replace("```json", "").replace("```", "")
        return json.loads(cleaned_response)
    except (json.JSONDecodeError, AttributeError):
        st.warning("Jakeiden automaattinen järjestely epäonnistui.")
        return None

def kirjoita_osio(aihe, osion_otsikko, jakeet, lisamateriaali, sanamaara_osio, malli, noudata_perusohjetta):
    jae_teksti = "\n".join(jakeet) if jakeet else "Ei Raamattu-jakeita tähän osioon."
    lisamateriaali_osio = f"\n\n--- KÄYTTÄJÄN ANTAMA LISÄMATERIAALI ---\n{lisamateriaali}" if lisamateriaali else ""
    prompt = f"Olet teologi. Kirjoita yksi kappale laajasta opetuksesta pääaiheella '{aihe}'. Kappaleen otsikko on: '{osion_otsikko}'. Kirjoita noin {sanamaara_osio} sanan osuus. ÄLÄ TOISTA OTSIKKOA. Aloita suoraan leipätekstillä. Käytä AINOASTAAN annettua KR33/38-lähdemateriaalia ja käyttäjän antamaa lisämateriaalia. Lainaa keskeiset jakeet sanatarkasti. LÄHDEMATERIAALI:\n{jae_teksti}{lisamateriaali_osio}"
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
        
# --- PÄÄOHJELMA ---
st.set_page_config(page_title="Älykäs Raamattu-tutkija", layout="wide")

if not st.session_state.password_correct:
    check_password()
else:
    st.title("📖 Älykäs Raamattu-tutkija v10.3")
    bible_data, book_map, book_name_map, book_data_map = lataa_raamattu()

    try:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    except (KeyError, FileNotFoundError):
        st.error("API-avainta ei löydy. Varmista, että olet asettanut GEMINI_API_KEY -salaisuuden Streamlitin asetuksissa.")
        st.stop()
    
    if not st.session_state.login_toast_shown:
        st.toast("Kirjautuminen onnistui!", icon="🎉")
        st.session_state.login_toast_shown = True

    if st.session_state.step == 'input':
        with st.sidebar:
            st.header("Asetukset")
            # MUUTOS: Tekstikentän korkeutta kasvatettu.
            aihe = st.text_area("Mistä aiheesta?", "Jumalan kutsu", height=250)
            ladatut_tiedostot = st.file_uploader("Lataa lisämateriaalia", type=['txt', 'pdf', 'docx'], accept_multiple_files=True)
            st.subheader("Haun asetukset")
            jakeita_ennen = st.slider("Jakeita ennen osumaa:", 0, 10, 1)
            jakeita_jalkeen = st.slider("Jakeita osuman jälkeen:", 0, 10, 2)
            st.subheader("Tekoälyn asetukset")
            malli_valinta_ui = st.selectbox("Valitse Gemini-malli:", ('gemini-1.5-flash', 'gemini-1.5-pro'))
            noudata_perusohjetta_luodessa = st.checkbox("Noudata teologista perusohjetta", value=True)
            
            if st.button("Aloita tutkimus", type="primary"):
                with st.spinner("Kerätään aineistoa..."):
                    st.session_state.aineisto = {
                        'aihe': aihe,
                        'malli': malli_valinta_ui,
                        'noudata_ohjetta': noudata_perusohjetta_luodessa
                    }
                    lisamateriaalit = [lue_ladattu_tiedosto(tiedosto) for tiedosto in ladatut_tiedostot] if ladatut_tiedostot else []
                    st.session_state.aineisto['lisamateriaali'] = "\n\n---\n\n".join(lisamateriaalit)

                    suunnitelma_prompt = f"Luo JSON-muodossa lista avainsanoista ('hakusanat') ja Raamatun kirjoista ('kirjat') aiheelle '{aihe}'."
                    suunnitelma_str = tee_api_kutsu(suunnitelma_prompt, 'gemini-1.5-flash', noudata_perusohjetta_luodessa)
                    try: suunnitelma = json.loads(suunnitelma_str.strip().replace("```json", "").replace("```", ""))
                    except: suunnitelma = {"hakusanat": aihe.split(), "kirjat": []}
                    
                    kaikki_loydetyt_jakeet = set()
                    for kirja in suunnitelma.get("kirjat", []):
                        for sana in suunnitelma.get("hakusanat", []):
                            for jae in etsi_ja_laajenna(bible_data, book_map, book_name_map, book_data_map, sana, kirja, jakeita_ennen, jakeita_jalkeen):
                                kaikki_loydetyt_jakeet.add(jae)
                    st.session_state.aineisto['jakeet'] = sorted(list(kaikki_loydetyt_jakeet))

                    sisallysluettelo_str = luo_sisallysluettelo(aihe, malli_valinta_ui, noudata_perusohjetta_luodessa)
                    st.session_state.aineisto['sisallysluettelo'] = sisallysluettelo_str
                    
                    st.session_state.step = 'review'
                    st.rerun()

    elif st.session_state.step == 'review':
        st.header("2. Tarkista ja muokkaa sisällysluetteloa")
        st.info("Tekoäly on luonut ehdotuksen sisällysluetteloksi ja kerännyt lähdemateriaalin. Voit nyt muokata sisällysluetteloa ennen lopullisen tekstin luomista.")
        
        muokattu_sisallysluettelo = st.text_area("Sisällysluettelo:", value=st.session_state.aineisto.get('sisallysluettelo', ''), height=300)
        
        st.subheader("Kerätty lähdemateriaali")
        with st.expander(f"Näytä {len(st.session_state.aineisto.get('jakeet', []))} löydettyä jaetta"):
            st.text_area("", value="\n".join(st.session_state.aineisto.get('jakeet', [])), height=300)

        with st.sidebar:
            st.header("Luo lopputulos")
            toimintatapa = st.radio("Mitä haluat tuottaa?", ("Valmis opetus (Optimoitu)", "Tutkimusraportti (Jatkojalostukseen)"))
            sanamaara = st.number_input("Tavoitesanamäärä (vain opetukselle)", min_value=300, max_value=20000, value=4000, step=100)
            
            if st.button("Luo lopputulos", type="primary"):
                st.session_state.aineisto['sisallysluettelo'] = muokattu_sisallysluettelo
                st.session_state.aineisto['toimintatapa'] = toimintatapa
                st.session_state.aineisto['sanamaara'] = sanamaara
                st.session_state.step = 'output'
                st.rerun()

    elif st.session_state.step == 'output':
        aineisto = st.session_state.aineisto
        lopputulos = ""

        if aineisto['toimintatapa'] == "Valmis opetus (Optimoitu)":
            with st.status("Kirjoitetaan opetusta...", expanded=True) as status:
                sisallysluettelo = [rivi.strip() for rivi in aineisto['sisallysluettelo'].split('\n') if rivi.strip()]
                
                status.write("Vaihe 1/2: Suodatetaan jakeita osioihin...")
                jae_kartta = jarjestele_jakeet_osioihin(aineisto['sisallysluettelo'], aineisto['jakeet'], 'gemini-1.5-flash', aineisto['noudata_ohjetta'])
                
                if jae_kartta:
                    suodatetut_jakeet = set()
                    for jakeet_listassa in jae_kartta.values():
                        for jae in jakeet_listassa:
                            suodatetut_jakeet.add(jae)
                    aineisto['suodatettu_jaemaara'] = len(suodatetut_jakeet)
                else:
                    aineisto['suodatettu_jaemaara'] = len(aineisto['jakeet'])
                
                status.write(f"Vaihe 2/2: Kirjoitetaan opetus osio kerrallaan...")
                koko_opetus, osioiden_maara = [], len(sisallysluettelo)
                sanamaara_per_osio = aineisto['sanamaara'] // osioiden_maara if osioiden_maara > 0 else aineisto['sanamaara']
                
                for i, otsikko in enumerate(sisallysluettelo):
                    relevantit_jakeet = jae_kartta.get(otsikko, aineisto['jakeet']) if jae_kartta else aineisto['jakeet']
                    osio_teksti = kirjoita_osio(aineisto['aihe'], otsikko, relevantit_jakeet, aineisto['lisamateriaali'], sanamaara_per_osio, aineisto['malli'], aineisto['noudata_ohjetta'])
                    if osio_teksti:
                        koko_opetus.append(f"### {otsikko}\n\n{osio_teksti}\n\n")
                lopputulos = "".join(koko_opetus)

        elif aineisto['toimintatapa'] == "Tutkimusraportti (Jatkojalostukseen)":
            with st.spinner("Kootaan raporttia..."):
                komentopohja = f"""
Hei, tässä on app.py-tutkimusapurini tuottama raportti. Tehtäväsi on kirjoittaa tämän aineiston pohjalta laadukas, syvällinen ja kielellisesti rikas opetus.
---
AIHE:
{aineisto['aihe']}
---
SISÄLLYSLUETTELO, JOTA TULEE NOUDATTAA:
{aineisto['sisallysluettelo']}
---
LÄHDEMATERIAALI (AINOAT SALLITUT JAKEET):
{"\n".join(aineisto['jakeet'])}
---
LISÄOHJEET:
Kirjoita noin [TÄYTÄ TAVOITESANAMÄÄRÄ TÄHÄN] sanan mittainen opetus. Käytä vivahteikasta kieltä ja varmista, että teologiset päätelmät ovat loogisia ja perustuvat ainoastaan annettuun materiaaliin. Voit hyödyntää syvätutkimus-toimintoa rikastamaan selityksiäsi, mutta älä tuo mukaan uusia jakeita tai ulkopuolisia oppijärjestelmiä.
"""
                lopputulos = komentopohja

        st.header("Valmis tuotos")
        
        # MUUTOS: Koko raportointilogiikka on uusittu selkeämmäksi.
        info_teksti = ""
        alkuperainen_maara = len(aineisto.get('jakeet', []))

        if aineisto.get('toimintatapa') == "Valmis opetus (Optimoitu)":
            sanojen_maara = len(lopputulos.split())
            suodatettu_maara = aineisto.get('suodatettu_jaemaara', alkuperainen_maara)
            info_teksti = f"Sanamäärä: **{sanojen_maara}** | Jakeita (Alkup. / Suodatettu): **{alkuperainen_maara} / {suodatettu_maara}**"
        else: # Tutkimusraportti-näkymä
            info_teksti = f"Jakeita kerätty yhteensä: **{alkuperainen_maara}**"
        
        st.info(info_teksti)
        st.download_button("Lataa tiedostona (.txt)", data=lopputulos, file_name="lopputulos.txt")
        st.text_area("Lopputulos:", value=lopputulos, height=600)

        if st.button("Uusi tutkimus"):
            st.session_state.step = 'input'
            st.session_state.aineisto = {}
            st.rerun()
