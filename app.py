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
</style>
""", unsafe_allow_html=True)

if 'password_correct' not in st.session_state:
    st.session_state.password_correct = False
if 'opetus_teksti' not in st.session_state:
    st.session_state.opetus_teksti = ""
if 'current_mode' not in st.session_state:
    st.session_state.current_mode = "opetus"


# --- TAUSTA-FUNKTIOT ---
@st.cache_data
def lataa_raamattu(tiedostonimi="bible.json"):
    try:
        with open(tiedostonimi, "r", encoding="utf-8") as f:
            bible_data = json.load(f)
    except FileNotFoundError:
        st.error(f"KRIITTINEN VIRHE: Tiedostoa '{tiedostonimi}' ei löytynyt.")
        st.stop()
    book_map, book_name_map = {}, {}
    for book_id, book_content in bible_data.get('book', {}).items():
        info, target = book_content.get('info', {}), (book_id, book_content)
        proper_name = info.get('name', f"Kirja {book_id}")
        book_name_map[book_id] = proper_name
        names = [info.get('name', ''), info.get('shortname', '')] + info.get('abbr', [])
        for name in names:
            if name:
                key = name.lower().replace('.', '').replace(' ', '')
                if key: book_map[key] = target
    return bible_data, book_map, book_name_map

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

def etsi_sana_paikallisesti(bible_data, book_map, book_name_map, sana, kirja):
    tulokset, sana_lower = [], sana.lower().replace('*', '.*')
    try: pattern = re.compile(sana_lower)
    except re.error: return []
    key_to_find = kirja.lower().replace('.', '').replace(' ', '')
    if key_to_find not in book_map: return []
    book_id_str, book_content = book_map[key_to_find]
    oikea_nimi = book_name_map.get(book_id_str, f"Kirja {book_id_str}")
    for luku, luku_data in book_content.get('chapter', {}).items():
        for jae_num, jae_data in luku_data.get('verse', {}).items():
            teksti = jae_data.get('text', '')
            if pattern.search(teksti.lower()):
                tulokset.append(f"{oikea_nimi} {luku}:{jae_num} - {teksti}")
    return tulokset

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

def paranna_tekstin_osaa(koko_teksti, muokattava_osa, ohje, malli, noudata_perusohjetta):
    if not muokattava_osa.strip():
        st.warning("Liitä ensin muokattava tekstinosa alempaan kenttään.")
        return None
    prompt = f"Olet kustannustoimittaja. Muokkaa alla olevasta KOKO TEKSTISTÄ yhtä osiota. KOKO TEKSTI (KONTEKSTIA VARTEN): --- {koko_teksti} --- MUOKATTAVA OSIO: --- {muokattava_osa} --- Käyttäjän ohje on: \"{ohje}\". PALAUTA AINOASTAAN UUSI, PARANNELTU VERSIO MUOKATTAVASTA OSIOSTA."
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
            if password == correct_password: st.session_state.password_correct = True; st.rerun()
            else: st.error("Salasana on virheellinen.")
    else: 
        st.session_state.password_correct = True

# --- PÄÄOHJELMA ---
st.set_page_config(page_title="Älykäs Raamattu-tutkija", layout="wide")

if not st.session_state.password_correct:
    check_password()
else:
    st.title("📖 Älykäs Raamattu-tutkija v8.1")
    bible_data, book_map, book_name_map = lataa_raamattu()

    try:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    except (KeyError, FileNotFoundError):
        st.error("API-avainta ei löydy. Varmista, että olet asettanut GEMINI_API_KEY -salaisuuden Streamlitin asetuksissa.")
        st.stop()

    with st.sidebar:
        st.success("Kirjautuminen onnistui!")
        st.header("Jatka aiempaa projektia")
        ladattu_projekti = st.file_uploader("Lataa projekti (.txt)", type=['txt'], key="projektin_lataus")
        if ladattu_projekti is not None:
            st.session_state.opetus_teksti = lue_ladattu_tiedosto(ladattu_projekti)
            st.session_state.current_mode = "opetus"
            st.rerun()

        st.divider()
        st.header("Luo uusi")
        
        toimintatapa = st.radio(
            "Mitä haluat tuottaa?",
            ("Valmis opetus (Kaikki vaiheet)", "Tutkimusraportti (Jatkojalostukseen)"),
            captions=("Ohjelma kirjoittaa valmiin opetuksen.", "Ohjelma kokoaa vain aineiston jatkojalostusta varten.")
        )

        aihe = st.text_area("Mistä aiheesta?", "Jumalan armo", height=100)
        ladatut_tiedostot = st.file_uploader("Lataa lisämateriaalia", type=['txt', 'pdf', 'docx'], accept_multiple_files=True)
        sanamaara = st.number_input("Tavoitesanamäärä (vain opetukselle)", min_value=300, max_value=20000, value=1000, step=100)
        malli_valinta_ui = st.selectbox("Valitse Gemini-malli:", ('gemini-1.5-pro', 'gemini-1.5-flash'))
        noudata_perusohjetta_luodessa = st.checkbox("Noudata teologista perusohjetta", value=True)
        suorita_nappi = st.button("Suorita", type="primary")

    if suorita_nappi:
        with st.status("Suoritetaan...", expanded=True) as status:
            status.write("[1/4] Luetaan ja etsitään aineistoa...")
            lisamateriaalit = [lue_ladattu_tiedosto(tiedosto) for tiedosto in ladatut_tiedostot] if ladatut_tiedostot else []
            lisamateriaali_teksti = "\n\n---\n\n".join(lisamateriaalit)
            suunnitelma_prompt = f"Luo JSON-muodossa lista avainsanoista ('hakusanat') ja Raamatun kirjoista ('kirjat') aiheelle '{aihe}'."
            suunnitelma_str = tee_api_kutsu(suunnitelma_prompt, 'gemini-1.5-flash', noudata_perusohjetta_luodessa)
            try: suunnitelma = json.loads(suunnitelma_str.strip().replace("```json", "").replace("```", ""))
            except: suunnitelma = {"hakusanat": aihe.split(), "kirjat": []}
            
            kaikki_loydetyt_jakeet = set()
            for kirja in suunnitelma.get("kirjat", []):
                for sana in suunnitelma.get("hakusanat", []):
                    for jae in etsi_sana_paikallisesti(bible_data, book_map, book_name_map, sana, kirja):
                        kaikki_loydetyt_jakeet.add(jae)
            status.write(f"-> Aineisto kerätty: {len(kaikki_loydetyt_jakeet)} jaetta löydetty.")

            status.write("[2/4] Luodaan sisällysluettelo...")
            sisallysluettelo_str = luo_sisallysluettelo(aihe, malli_valinta_ui, noudata_perusohjetta_luodessa)
            if not sisallysluettelo_str: st.stop()
            sisallysluettelo = [rivi.strip() for rivi in sisallysluettelo_str.split('\n') if rivi.strip()]

            if toimintatapa == "Luo valmis opetus (Kaikki vaiheet)":
                st.session_state.current_mode = "opetus"
                status.write("[3/4] Järjestellään jakeita osioihin...")
                jae_kartta = jarjestele_jakeet_osioihin(sisallysluettelo_str, list(kaikki_loydetyt_jakeet), 'gemini-1.5-flash', noudata_perusohjetta_luodessa)

                status.write("[4/4] Kirjoitetaan opetus osio kerrallaan...")
                koko_opetus, osioiden_maara = [], len(sisallysluettelo)
                sanamaara_per_osio = sanamaara // osioiden_maara if osioiden_maara > 0 else sanamaara
                progress_bar = st.progress(0)
                for i, otsikko in enumerate(sisallysluettelo):
                    status.update(label=f"Kirjoitetaan osiota {i+1}/{osioiden_maara}...")
                    relevantit_jakeet = jae_kartta.get(otsikko, list(kaikki_loydetyt_jakeet)) if jae_kartta else list(kaikki_loydetyt_jakeet)
                    osio_teksti = kirjoita_osio(aihe, otsikko, relevantit_jakeet, lisamateriaali_teksti, sanamaara_per_osio, malli_valinta_ui, noudata_perusohjetta_luodessa)
                    if osio_teksti: koko_opetus.append(f"### {otsikko}\n\n{osio_teksti}\n\n")
                    progress_bar.progress((i + 1) / osioiden_maara)
                
                st.session_state.opetus_teksti = "".join(koko_opetus)
                st.session_state.malli_valinta_muokkaus = malli_valinta_ui
                status.update(label="Opetus valmis!", state="complete")

            elif toimintatapa == "Tutkimusraportti (Jatkojalostukseen)":
                st.session_state.current_mode = "raportti"
                status.write("[3/4] Kootaan tutkimusraporttia...")
                
                # --- UUSI LISÄYS: Luodaan valmis komentopohja ---
                komentopohja = f"""
Hei, tässä on app.py-tutkimusapurini tuottama raportti. Tehtäväsi on kirjoittaa tämän aineiston pohjalta laadukas, syvällinen ja kielellisesti rikas opetus.

---
AIHE:
{aihe}

---
SISÄLLYSLUETTELO, JOTA TULEE NOUDATTAA:
{sisallysluettelo_str}

---
LÄHDEMATERIAALI (AINOAT SALLITUT JAKEET):
{"\n".join(sorted(list(kaikki_loydetyt_jakeet)))}

---
LISÄOHJEET:
Kirjoita noin [TÄYTÄ TAVOITESANAMÄÄRÄ TÄHÄN] sanan mittainen opetus. Käytä vivahteikasta kieltä ja varmista, että teologiset päätelmät ovat loogisia ja perustuvat ainoastaan annettuun materiaaliin. Voit hyödyntää syvätutkimus-toimintoa rikastamaan selityksiäsi, mutta älä tuo mukaan uusia jakeita tai ulkopuolisia oppijärjestelmiä.
"""
                st.session_state.opetus_teksti = komentopohja
                status.update(label="Tutkimusraportti ja komentopohja valmiit!", state="complete")
            
            st.rerun()

    # --- TULOSTEN NÄYTTÖ JA MUOKKAUS ---
    if st.session_state.opetus_teksti:
        header_text = "Työstettävä opetus" if st.session_state.current_mode == "opetus" else "Valmis tutkimusraportti / Komentopohja"
        st.header(header_text)
        
        sanojen_maara = len(st.session_state.opetus_teksti.split())
        st.download_button(
            label=f"Lataa {st.session_state.current_mode} tiedostona (.txt)",
            data=st.session_state.opetus_teksti,
            file_name=f"{st.session_state.current_mode}.txt",
            mime="text/plain"
        )

        st.text_area("Lopputulos:", value=st.session_state.opetus_teksti, height=600, key="editori")
        
        if st.session_state.current_mode == "opetus":
            st.header("Muokkaa osiota")
            st.warning("**Ohje:** Kopioi osa yllä olevasta tekstistä alempaan 'Muokattava osa' -kenttään, anna ohje ja paina 'Paranna'.")
            col3, col4 = st.columns(2)
            with col3:
                muokattava_osio = st.text_area("Liitä tähän se tekstin osa, jota haluat muokata:", height=200)
            with col4:
                muokkaus_ohje = st.text_area("Anna tekoälylle muokkausohje:", height=125)
                noudata_perusohjetta_muokatessa = st.checkbox("Noudata teologista perusohjetta muokatessa", value=True)
                paranna_nappi = st.button("Paranna tekstinosaa", type="primary")

            if paranna_nappi and muokkaus_ohje and muokattava_osio:
                malli = st.session_state.get("malli_valinta_muokkaus", "gemini-1.5-flash")
                with st.spinner("Tekoäly muokkaa tekstinosaa..."):
                    paranneltu_osio = paranna_tekstin_osaa(st.session_state.editori, muokattava_osio, muokattava_osa, ohje, malli, noudata_perusohjetta_muokatessa)
                    if paranneltu_osio and paranneltu_osio.strip() != muokattava_osio.strip():
                        st.session_state.opetus_teksti = st.session_state.editori.replace(muokattava_osio, paranneltu_osio, 1)
                        st.rerun()
                    elif paranneltu_osio:
                        st.warning("Tekoäly ei tehnyt muutoksia.")
        
        if st.session_state.editori != st.session_state.opetus_teksti:
            st.session_state.opetus_teksti = st.session_state.editori

