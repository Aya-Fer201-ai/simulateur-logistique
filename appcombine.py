# app.py (Version avec correction du ValueError)
import streamlit as st
import pandas as pd
from io import BytesIO
import sys
from io import StringIO

# On importe votre code comme un module
try:
    import combainaisonexceldescente as sim
except ImportError:
    st.error("ERREUR: Le fichier 'simulation_logic.py' est introuvable. Assurez-vous qu'il est dans le même dossier que 'app.py'.")
    st.stop()


# --- Fonctions Helper ---

@st.cache_data
def load_and_clean_data_from_uploads(relations_file, origins_file, destinations_file):
    """Charge et nettoie les données à partir des fichiers téléversés."""
    try:
        def clean_numeric_column(series):
            return series.astype(str).str.replace('\u202f', '', regex=False).str.replace(',', '.', regex=False).str.strip()

        relations_df = pd.read_csv(relations_file, dtype=str)
        relations_df['origin'] = relations_df['origin'].str.strip()
        relations_df['destination'] = relations_df['destination'].str.strip()
        relations_df['distance_km'] = clean_numeric_column(relations_df['distance_km']).astype(float)
        relations_df['profitability'] = clean_numeric_column(relations_df['profitability']).astype(int)
        
        origins_df_raw = pd.read_csv(origins_file, dtype=str)
        origins_df_raw['id'] = origins_df_raw['id'].str.strip()
        origins_df_raw['daily_loading_capacity_tons'] = clean_numeric_column(origins_df_raw['daily_loading_capacity_tons']).astype(float)
        origins_df_raw['initial_available_product_tons'] = clean_numeric_column(origins_df_raw['initial_available_product_tons']).astype(float)
        origins_df = origins_df_raw.set_index('id')
        
        destinations_df_raw = pd.read_csv(destinations_file, dtype=str)
        destinations_df_raw['id'] = destinations_df_raw['id'].str.strip()
        destinations_df_raw['daily_unloading_capacity_tons'] = clean_numeric_column(destinations_df_raw['daily_unloading_capacity_tons']).astype(float)
        destinations_df_raw['annual_demand_tons'] = clean_numeric_column(destinations_df_raw['annual_demand_tons']).astype(float)
        destinations_df = destinations_df_raw.set_index('id')
        
        return relations_df, origins_df, destinations_df
    except Exception as e:
        st.error(f"Erreur lors de la lecture des fichiers CSV : {e}")
        return None, None, None

def generate_list_from_config(df, config_tuple):
    """Traduit un critère de tri en une liste de destinations."""
    if not isinstance(config_tuple, tuple) or len(config_tuple) != 2:
        return df.index.tolist()
    sort_column, ascending_order = config_tuple
    df_copy = df.copy()
    if 'q_min_initial_target_tons' not in df_copy.columns and 'annual_demand_tons' in df_copy.columns:
        df_copy['q_min_initial_target_tons'] = df_copy['annual_demand_tons'] * 0.20
    if sort_column not in df_copy.columns:
        return df_copy.index.tolist()
    return df_copy.sort_values(by=sort_column, ascending=ascending_order).index.tolist()

def create_excel_download(sim_results, origins_initial_df_ref, destinations_initial_df_ref):
    """Crée un fichier Excel en mémoire pour le téléchargement."""
    output = BytesIO()
    try:
        sim.ecrire_resultats_excel(output, "resultats_simulation", sim_results, origins_initial_df_ref, destinations_initial_df_ref)
    except Exception:
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            if sim_results.get('shipments_df') is not None:
                sim_results.get('shipments_df').to_excel(writer, sheet_name="Expeditions", index=False)
    processed_data = output.getvalue()
    return processed_data
    
# --- Interface Streamlit ---

st.set_page_config(layout="wide", page_title="Simulateur & Optimiseur Logistique")
st.title("🚢 Simulateur & Optimiseur Logistique")

if 'results' not in st.session_state:
    st.session_state.results = None
if 'log_optim' not in st.session_state:
    st.session_state.log_optim = ""

st.sidebar.header("Configuration")

st.sidebar.subheader("1. Fichiers de Données (.csv)")
relations_file = st.sidebar.file_uploader("Relations", type="csv")
origins_file = st.sidebar.file_uploader("Origines", type="csv")
destinations_file = st.sidebar.file_uploader("Destinations", type="csv")

if relations_file and origins_file and destinations_file:
    relations_df, origins_df, destinations_df = load_and_clean_data_from_uploads(relations_file, origins_file, destinations_file)
    
    if relations_df is not None:
        st.sidebar.success("✅ Fichiers chargés.")
        st.sidebar.subheader("2. Paramètres Globaux")
        num_wagons = st.sidebar.number_input("Nombre de wagons initiaux", 10, 5000, 500, 10)
        st.sidebar.subheader("3. Mode d'Exécution")
        mode_choice = st.sidebar.radio("Mode :", ("Simulation Simple", "Optimisation (Montée)"), horizontal=True, label_visibility="collapsed")
        st.sidebar.subheader("4. Choix de l'Heuristique")
        heuristique_choice = st.sidebar.radio("Heuristique", ("H1", "H2"), horizontal=True, key="heuristique_choice")
        
        if mode_choice == "Simulation Simple":
            st.sidebar.subheader("5. Stratégie de Priorisation")
            section_title = "Critères de tri fixes"
        else:
            st.sidebar.subheader("5. Point de Départ de l'Optimisation")
            section_title = "Ordres de départ pour la montée"
            max_iter = st.sidebar.number_input("Nombre max d'itérations", 1, 100, 10)

        sort_options = {"Demande annuelle (décroissant)": ('annual_demand_tons', False), "QMIN (décroissant)": ('q_min_initial_target_tons', False), "Demande annuelle (croissant)": ('annual_demand_tons', True), "QMIN (croissant)": ('q_min_initial_target_tons', True)}
        st.sidebar.write(f"**{section_title}**")
        qmin_sort_choice = st.sidebar.selectbox("Ordre QMIN:", sort_options.keys(), key="qmin_order")
        phase2_sort_choice = st.sidebar.selectbox("Ordre Phase 2:", sort_options.keys(), key="phase2_order")
        start_qmin_config = sort_options[qmin_sort_choice]
        start_phase2_config = sort_options[phase2_sort_choice]
        
        if st.sidebar.button("🚀 Lancer l'Exécution", use_container_width=True):
            st.session_state.log_optim = ""
            with st.spinner("Exécution en cours..."):
                if mode_choice == "Simulation Simple":
                    if heuristique_choice == "H1":
                        final_sim_results = sim.run_simulation_h1(relations_df, origins_df, destinations_df, qmin_common_config=start_qmin_config, phase2_config=start_phase2_config, num_initial_wagons_param=num_wagons, silent_mode=True)
                    else:
                        qmin_list = generate_list_from_config(destinations_df, start_qmin_config); phase2_list = generate_list_from_config(destinations_df, start_phase2_config)
                        final_sim_results = sim.run_simulation_h2(relations_df, origins_df, destinations_df, qmin_user_priority_order=qmin_list, standard_shipment_dest_priority_order=phase2_list, num_initial_wagons_param=num_wagons, silent_mode=True)
                else:
                    st.session_state.log_optim += f"Lancement optim. {heuristique_choice} / {max_iter} itérations...\n"
                    start_qmin_list = generate_list_from_config(destinations_df, start_qmin_config); start_phase2_list = generate_list_from_config(destinations_df, start_phase2_config)
                    st.session_state.log_optim += f"Départ QMIN: {start_qmin_list}\nDépart Phase 2: {start_phase2_list}\n\n"
                    old_stdout = sys.stdout; sys.stdout = captured_output = StringIO()
                    if heuristique_choice == 'H1':
                        start_qmin_h1_config = ('custom_order', start_qmin_list); start_phase2_h1_config = ('custom_order', start_phase2_list)
                        best_qmin_cfg, _, best_phase2_cfg = sim.hill_climbing_maximizer_h1(relations_df, origins_df, destinations_df, start_qmin_h1_config, start_phase2_h1_config, num_wagons, max_iter)
                        final_sim_results = sim.run_simulation_h1(relations_df, origins_df, destinations_df, best_qmin_cfg, best_phase2_cfg, num_wagons, silent_mode=True)
                    else:
                        best_qmin_order, best_phase2_order = sim.hill_climbing_maximizer_h2(relations_df, origins_df, destinations_df, start_qmin_list, start_phase2_list, num_wagons, max_iter)
                        final_sim_results = sim.run_simulation_h2(relations_df, origins_df, destinations_df, best_qmin_order, best_phase2_order, num_wagons, silent_mode=True)
                    sys.stdout = old_stdout
                    st.session_state.log_optim += captured_output.getvalue()
            st.session_state.results = final_sim_results
            st.session_state.initial_data = (origins_df.copy(), destinations_df.copy())
            st.rerun()
else:
    st.info("👋 Bienvenue ! Veuillez téléverser les 3 fichiers CSV dans la barre latérale pour commencer.")

# --- Affichage des Résultats ---
if st.session_state.results:
    res = st.session_state.results
    st.header("📊 Résultats de l'Exécution")
    
    if st.session_state.log_optim:
        with st.expander("Voir le journal de l'optimisation", expanded=False):
            st.code(st.session_state.log_optim, language="bash")

    col1, col2, col3 = st.columns(3)
    col1.metric("Profit Final (Tonnes * km)", f"{res.get('profit', 0):,.0f}".replace(',', ' '))
    col2.metric("Jours de simulation", f"{res.get('days_taken_simulation_loop', 'N/A')}")
    col3.metric("Demande satisfaite ?", "✅ Oui" if res.get('all_demand_met', False) else "❌ Non")
    
    initial_orig, initial_dest = st.session_state.initial_data
    excel_data = create_excel_download(res, initial_orig, initial_dest)
    st.download_button("📥 Télécharger le rapport complet (Excel)", excel_data, "resultats_simulation.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

    shipments_df = res.get('shipments_df')
    final_dest_df = res.get('final_destinations_df')
    final_orig_df = res.get('final_origins_df')
    
    tab_graph, tab_transport, tab_dest, tab_orig, tab_wagon = st.tabs(["📈 Graphiques & KPIs", "Transport (Détail)", "Récap. Destinations", "Récap. Origines", "Suivi des Wagons"])

    with tab_graph:
        st.subheader("Analyse Visuelle des Résultats")
        if shipments_df is not None and not shipments_df.empty:
            col1_graph, col2_graph = st.columns(2)
            
            with col1_graph:
                st.write("**Quantité totale livrée par destination**")
                tons_per_dest = shipments_df.groupby('destination')['quantity_tons'].sum().sort_values(ascending=False)
                st.bar_chart(tons_per_dest)

                st.write("**Quantité totale expédiée par origine**")
                tons_per_origin = shipments_df.groupby('origin')['quantity_tons'].sum().sort_values(ascending=False)
                st.bar_chart(tons_per_origin)

            with col2_graph:
                st.write("**Taux de satisfaction de la demande (%)**")
                ### CORRECTION ###
                # On travaille directement avec final_dest_df qui contient déjà toutes les colonnes nécessaires.
                if final_dest_df is not None:
                    # On s'assure que les colonnes nécessaires existent pour éviter les erreurs
                    if 'annual_demand_tons' in final_dest_df.columns and 'delivered_so_far_tons' in final_dest_df.columns:
                        recap_df = final_dest_df.copy()
                        # Éviter la division par zéro si la demande est nulle
                        recap_df['satisfaction_rate'] = recap_df.apply(
                            lambda row: (row['delivered_so_far_tons'] / row['annual_demand_tons'] * 100) if row['annual_demand_tons'] > 0 else 0,
                            axis=1
                        ).fillna(0)
                        st.bar_chart(recap_df['satisfaction_rate'])
                    else:
                        st.warning("Colonnes 'annual_demand_tons' ou 'delivered_so_far_tons' manquantes pour le graphique de satisfaction.")
                else:
                    st.warning("Données de destination manquantes pour ce graphique.")
            
            st.write("**Flux d'expédition par jour (en tonnes)**")
            tons_per_day = shipments_df.groupby('ship_day')['quantity_tons'].sum()
            st.line_chart(tons_per_day)
        else:
            st.info("Aucune expédition n'a été réalisée, impossible de générer les graphiques.")

    with tab_transport:
        st.subheader("Détail de toutes les Expéditions (Tableau de Transport)")
        if shipments_df is not None and not shipments_df.empty:
            st.dataframe(shipments_df.style.format(precision=2))

    with tab_dest:
        st.subheader("État Final par Destination")
        if final_dest_df is not None:
            st.dataframe(final_dest_df.style.format(precision=2))

    with tab_orig:
        st.subheader("État Final par Origine")
        if final_orig_df is not None:
            st.dataframe(final_orig_df.style.format(precision=2))
            
    with tab_wagon:
        st.subheader("Suivi Quotidien des Wagons")
        tracking_vars = res.get('final_tracking_vars')
        if tracking_vars:
            wagon_log_df = pd.DataFrame(tracking_vars.get('daily_wagon_log', []))
            if not wagon_log_df.empty:
                st.line_chart(wagon_log_df.set_index('day'), y=['available_start', 'in_transit_end'])
                with st.expander("Voir les données détaillées du suivi"):
                    st.dataframe(wagon_log_df)
       
