import streamlit as st
import json
import sys
import re
import google.generativeai as genai
import time

# (Teologinen perusohje ja CSS-muotoilut pysyvät samoina)
TEOLOGINEN_PERUSOHJE = """
TÄRKEÄ PERUSOHJE: Olet teologinen assistentti, jonka ainoa ja tärkein tehtävä on auttaa käyttäjää ymmärtämään annettua Raamatun tekstiä sen omassa kontekstissa ja Raamatun kokonaisilmoituksen valossa.
Noudata seuraavia sääntöjä ehdottomasti:
1. Pysy lähteessä: Perusta KAIKKI vastauksesi ja tulkintasi AINOASTAAN sinulle annettuihin KR33/38-raamatunjakeisiin.
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
if 'password_correct' not in st.session_state:
    st.session_state.password_correct = False
if 'opetus_teksti' not in st.session_state:
    st.session_state.opetus_teksti = ""

# --- TAUSTA-FUNKTIOT (pysyvät samoina) ---
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

def luo_sisallysluettelo(aihe, sanamaara, malli, noudata_perusohjetta):
    prompt = f"Olet teologi. Luo yksityiskohtainen sisällysluettelo noin {sanamaara} sanan opetukselle aiheesta '{aihe}'. Rakenna runko, jossa on johdanto, 3-5 pääkohtaa ja jokaiseen 2-4 alakohtaa, sekä yhteenveto. Vastaa AINOASTAAN numeroituna listana."
    return tee_api_kutsu(prompt, malli, noudata_perusohjetta)

def kirjoita_osio(aihe, osion_otsikko, jakeet, sanamaara_osio, malli, noudata_perusohjetta):
    jae_teksti = "\n".join(jakeet) if jakeet else "Ei erityisiä jakeita tähän osioon."
    prompt = f"Olet teologi. Kirjoita yksi kappale laajasta opetuksesta pääaiheella '{aihe}'. Kappaleen otsikko on: '{osion_otsikko}'. Kirjoita noin {sanamaara_osio} sanan osuus. ÄLÄ TOISTA OTSIKKOA. Aloita suoraan leipätekstillä. Käytä AINOASTAAN annettua KR33/38-lähdemateriaalia ja lainaa keskeiset jakeet sanatarkasti. LÄHDEMATERIAALI:\n{jae_teksti}"
    return tee_api_kutsu(prompt, malli, noudata_perusohjetta)

def paranna_tekstin_osaa(koko_teksti, muokattava_osa, ohje, malli, noudata_perusohjetta):
    if not muokattava_osa.strip():
        st.warning("Liitä ensin muokattava tekstinosa alempaan kenttään.")
        return None
    prompt = f"Olet kustannustoimittaja. Muokkaa alla olevasta KOKO TEKSTISTÄ yhtä osiota. KOKO TEKSTI (KONTEKSTIA VARTEN): --- {koko_teksti} --- MUOKATTAVA OSIO: --- {muokattava_osa} --- Käyttäjän ohje on: \"{ohje}\". PALAUTA AINOASTAAN UUSI, PARANNELTU VERSIO MUOKATTAVASTA OSIOSTA."
    return tee_api_kutsu(prompt, malli, noudata_perusohjetta)

# --- SISÄÄNKIRJAUTUMISLOGIIKKA ---

def check_password():
    st.header("🔑 Kirjaudu sisään")
    password = st.text_input("Syötä salasana", type="password")
    
    # Tarkistetaan, onko salasanaa asetettu Streamlitin salaisuuksiin
    # Jos ei, ohjelma ei voi toimia julkisesti, mutta toimii paikallisesti ilman salasanaa
    try:
        correct_password = st.secrets["APP_PASSWORD"]
        is_public_env = True
    except (KeyError, FileNotFoundError):
        is_public_env = False

    if is_public_env:
        if st.button("Kirjaudu"):
            if password == correct_password:
                st.session_state.password_correct = True
                st.rerun()
            else:
                st.error("Salasana on virheellinen.")
    else: # Paikallisessa ajossa ei vaadita salasanaa
        st.session_state.password_correct = True

# --- PÄÄOHJELMA ---

st.set_page_config(page_title="Älykäs Raamattu-tutkija", layout="wide")

if not st.session_state.password_correct:
    check_password()
else:
    st.title("📖 Älykäs Raamattu-tutkija v3.6")
    bible_data, book_map, book_name_map = lataa_raamattu()

    # KORJATTU API-AVAIMEN KÄSITTELY
    try:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    except (KeyError, FileNotFoundError):
        st.error("API-avainta ei löydy. Jos ajat ohjelmaa julkisesti, varmista että olet asettanut GEMINI_API_KEY -salaisuuden Streamlitin asetuksissa. Jos ajat paikallisesti, tarvitset .streamlit/secrets.toml -tiedoston.")
        st.stop()


    with st.sidebar:
        st.success("Kirjautuminen onnistui!")
        st.header("1. Luo uusi opetus")
        aihe = st.text_area("Mistä aiheesta haluat luoda opetuksen?", "Jumalan kutsu", height=100)
        sanamaara = st.number_input("Mikä on tavoitesanamäärä?", min_value=300, max_value=20000, value=1000, step=100)
        malli_valinta_ui = st.selectbox("Valitse Gemini-malli:", ('gemini-1.5-pro', 'gemini-1.5-flash'))
        noudata_perusohjetta_luodessa = st.checkbox("Noudata teologista perusohjetta", value=True, help="Pakottaa tekoälyn pysymään Raamatun tekstissä ja välttämään oppisuuntauksia.")
        suorita_nappi = st.button("Luo opetus", type="primary")

    if suorita_nappi:
        with st.status("Luodaan opetusta...", expanded=True) as status:
            status.write("[1/4] Luodaan hakusanat...")
            suunnitelma_prompt = f"Luo JSON-muodossa lista avainsanoista ('hakusanat') ja Raamatun kirjoista ('kirjat') aiheelle '{aihe}'."
            suunnitelma_str = tee_api_kutsu(suunnitelma_prompt, 'gemini-1.5-flash', noudata_perusohjetta_luodessa)
            try: suunnitelma = json.loads(suunnitelma_str.strip().replace("```json", "").replace("```", ""))
            except: suunnitelma = {"hakusanat": aihe.split(), "kirjat": []}
            status.write("[2/4] Etsitään jakeita...")
            kaikki_loydetyt_jakeet = set()
            for kirja in suunnitelma.get("kirjat", []):
                for sana in suunnitelma.get("hakusanat", []):
                    for jae in etsi_sana_paikallisesti(bible_data, book_map, book_name_map, sana, kirja):
                        kaikki_loydetyt_jakeet.add(jae)
            status.write(f"-> Löydetty {len(kaikki_loydetyt_jakeet)} jaetta.")
            status.write("[3/4] Luodaan sisällysluettelo...")
            sisallysluettelo_str = luo_sisallysluettelo(aihe, sanamaara, malli_valinta_ui, noudata_perusohjetta_luodessa)
            if not sisallysluettelo_str: st.stop()
            sisallysluettelo = [rivi.strip() for rivi in sisallysluettelo_str.split('\n') if rivi.strip()]
            status.write("[4/4] Kirjoitetaan opetus osio kerrallaan...")
            koko_opetus, osioiden_maara = [], len(sisallysluettelo)
            sanamaara_per_osio = sanamaara // osioiden_maara if osioiden_maara > 0 else sanamaara
            progress_bar = st.progress(0)
            for i, otsikko in enumerate(sisallysluettelo):
                status.update(label=f"Kirjoitetaan osiota {i+1}/{osioiden_maara}: \"{otsikko}\"...")
                osio_teksti = kirjoita_osio(aihe, otsikko, list(kaikki_loydetyt_jakeet), sanamaara_per_osio, malli_valinta_ui, noudata_perusohjetta_luodessa)
                if osio_teksti: koko_opetus.append(f"### {otsikko}\n\n{osio_teksti}\n\n")
                progress_bar.progress((i + 1) / osioiden_maara)
            st.session_state.opetus_teksti = "".join(koko_opetus)
            st.session_state.malli_valinta_muokkaus = malli_valinta_ui
            status.update(label="Opetus valmis!", state="complete")
            st.rerun()

    if st.session_state.opetus_teksti:
        st.header("2. Koko opetus")
        sanojen_maara = len(st.session_state.opetus_teksti.split())
        col1, col2 = st.columns([3, 1])
        with col1:
            st.info(f"Nykyinen sanamäärä: **{sanojen_maara}** | Kopioi kaikki: **Ctrl+A**, sitten **Ctrl+C**")
        with col2:
            st.download_button(label="Lataa tekstitiedostona (.txt)", data=st.session_state.opetus_teksti, file_name=f"opetus.txt", mime="text/plain")
        
        st.text_area("Valmis teksti:", value=st.session_state.opetus_teksti, height=400, key="editori")
        st.header("3. Muokkaa osiota")
        st.warning("**Ohje:** Kopioi osa yllä olevasta tekstistä alempaan 'Muokattava osa' -kenttään, anna ohje ja paina 'Paranna'.")
        col3, col4 = st.columns(2)
        with col3:
            muokattava_osio = st.text_area("Liitä tähän se tekstin osa, jota haluat muokata:", height=200, placeholder="1. Kopioi osa yltä\n2. Liitä se tähän")
        with col4:
            muokkaus_ohje = st.text_area("Anna tekoälylle muokkausohje:", height=125, placeholder="Esim. 'Tee tästä kappaleesta runollisempi'")
            noudata_perusohjetta_muokatessa = st.checkbox("Noudata teologista perusohjetta", value=True)
            paranna_nappi = st.button("Paranna tekstinosaa", type="primary")

        if paranna_nappi and muokkaus_ohje and muokattava_osio:
            malli = st.session_state.get("malli_valinta_muokkaus", "gemini-1.5-flash")
            with st.spinner("Tekoäly muokkaa tekstinosaa..."):
                paranneltu_osio = paranna_tekstin_osaa(st.session_state.editori, muokattava_osio, muokkaus_ohje, malli, noudata_perusohjetta_muokatessa)
                if paranneltu_osio and paranneltu_osio.strip() != muokattava_osio.strip():
                    st.session_state.opetus_teksti = st.session_state.editori.replace(muokattava_osio, paranneltu_osio, 1)
                    st.rerun()
                elif paranneltu_osio:
                    st.warning("Tekoäly ei tehnyt muutoksia tekstiin. Yritä antaa yksityiskohtaisempi tai erilainen ohje.")
        
        if st.session_state.editori != st.session_state.opetus_teksti:
            st.session_state.opetus_teksti = st.session_state.editori
