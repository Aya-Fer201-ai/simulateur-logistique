import streamlit as st
import pandas as pd
from io import BytesIO
import sys
from io import StringIO

# On importe votre code comme un module
# Assurez-vous que votre fichier de simulation s'appelle 'simulation_logic.py'
# et qu'il est dans le même dossier.
try:
    import combainaisonexceldescente as sim
except ImportError:
    st.error("ERREUR: Le fichier 'simulation_logic.py' est introuvable. Assurez-vous qu'il est dans le même dossier que 'app.py'.")
    st.stop()


# --- Fonctions Helper pour l'interface ---

@st.cache_data
def load_and_clean_data_from_uploads(relations_file, origins_file, destinations_file):
    """Charge et nettoie les données à partir des fichiers téléversés par l'utilisateur."""
    try:
        # Votre fonction de nettoyage originale, adaptée pour fonctionner avec des fichiers en mémoire
        def clean_numeric_column(series):
            return series.astype(str).str.replace('\u202f', '', regex=False).str.replace(',', '.', regex=False).str.strip()

        # Relations
        relations_df = pd.read_csv(relations_file, dtype=str)
        relations_df['origin'] = relations_df['origin'].str.strip()
        relations_df['destination'] = relations_df['destination'].str.strip()
        relations_df['distance_km'] = clean_numeric_column(relations_df['distance_km']).astype(float)
        relations_df['profitability'] = clean_numeric_column(relations_df['profitability']).astype(int)
        
        # Origines
        origins_df_raw = pd.read_csv(origins_file, dtype=str)
        origins_df_raw['id'] = origins_df_raw['id'].str.strip()
        origins_df_raw['daily_loading_capacity_tons'] = clean_numeric_column(origins_df_raw['daily_loading_capacity_tons']).astype(float)
        origins_df_raw['initial_available_product_tons'] = clean_numeric_column(origins_df_raw['initial_available_product_tons']).astype(float)
        origins_df = origins_df_raw.set_index('id')
        
        # Destinations
        destinations_df_raw = pd.read_csv(destinations_file, dtype=str)
        destinations_df_raw['id'] = destinations_df_raw['id'].str.strip()
        destinations_df_raw['daily_unloading_capacity_tons'] = clean_numeric_column(destinations_df_raw['daily_unloading_capacity_tons']).astype(float)
        destinations_df_raw['annual_demand_tons'] = clean_numeric_column(destinations_df_raw['annual_demand_tons']).astype(float)
        destinations_df = destinations_df_raw.set_index('id')
        
        return relations_df, origins_df, destinations_df
    except Exception as e:
        st.error(f"Erreur lors de la lecture ou du nettoyage des fichiers CSV : {e}")
        st.warning("Veuillez vérifier que les colonnes de vos fichiers correspondent au format attendu (id, distance_km, etc.).")
        return None, None, None

def generate_list_from_config(df, config_tuple):
    """
    Traduit un critère de tri (style H1) en une liste de destinations triée (pour H2 ou pour le départ de la montée).
    """
    if not isinstance(config_tuple, tuple) or len(config_tuple) != 2:
        return df.index.tolist()
        
    sort_column, ascending_order = config_tuple
    df_copy = df.copy()
    
    # Ajoute les colonnes de calcul nécessaires pour le tri si elles n'existent pas
    if 'q_min_initial_target_tons' not in df_copy.columns and 'annual_demand_tons' in df_copy.columns:
        df_copy['q_min_initial_target_tons'] = df_copy['annual_demand_tons'] * 0.20
        
    if sort_column not in df_copy.columns:
        st.error(f"La colonne de tri '{sort_column}' est introuvable. Utilisation de l'ordre par défaut.")
        return df_copy.index.tolist()
        
    return df_copy.sort_values(by=sort_column, ascending=ascending_order).index.tolist()

def create_excel_download(sim_results, origins_initial_df_ref, destinations_initial_df_ref):
    """
    Crée un fichier Excel en mémoire à partir des résultats de la simulation en utilisant
    votre fonction d'écriture originale.
    """
    output = BytesIO()
    try:
        # On tente d'appeler votre fonction d'écriture originale
        sim.ecrire_resultats_excel(
            chemin_fichier_excel=output,
            nom_feuille_sortie="resultats_simulation",
            sim_results=sim_results,
            origins_initial_df_ref=origins_initial_df_ref,
            destinations_initial_df_ref=destinations_initial_df_ref
        )
    except Exception as e:
        # En cas d'échec, on utilise une méthode de secours simple
        st.warning(f"L'écriture Excel via la fonction originale a échoué ({e}), un rapport simplifié est généré.")
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            if sim_results and sim_results.get('shipments_df') is not None:
                sim_results.get('shipments_df').to_excel(writer, sheet_name="Expeditions", index=False)
            if sim_results and sim_results.get('final_destinations_df') is not None:
                sim_results.get('final_destinations_df').to_excel(writer, sheet_name="Recap_Destinations")
    
    processed_data = output.getvalue()
    return processed_data

# --- Début de l'Interface Streamlit ---

st.set_page_config(layout="wide", page_title="Simulateur & Optimiseur Logistique")
st.title("🚢 Simulateur & Optimiseur Logistique")

# Initialisation des variables de session pour garder l'état entre les rechargements
if 'results' not in st.session_state:
    st.session_state.results = None
if 'log_optim' not in st.session_state:
    st.session_state.log_optim = ""

# --- Barre Latérale de Configuration ---
st.sidebar.header("Configuration")

# 1. Téléversement des fichiers
st.sidebar.subheader("1. Fichiers de Données (.csv)")
relations_file = st.sidebar.file_uploader("Relations", type="csv", help="Fichier contenant les origines, destinations, distances et rentabilité.")
origins_file = st.sidebar.file_uploader("Origines", type="csv", help="Fichier contenant les informations sur les sites de production.")
destinations_file = st.sidebar.file_uploader("Destinations", type="csv", help="Fichier contenant les informations sur les sites de livraison.")

# La suite de l'interface ne s'affiche que si tous les fichiers sont chargés
if relations_file and origins_file and destinations_file:
    # Chargement et nettoyage des données
    relations_df, origins_df, destinations_df = load_and_clean_data_from_uploads(
        relations_file, origins_file, destinations_file
    )
    
    # Si le chargement a réussi
    if relations_df is not None:
        st.sidebar.success("✅ Fichiers chargés et validés.")
        
        # 2. Paramètres généraux
        st.sidebar.subheader("2. Paramètres Globaux")
        num_wagons = st.sidebar.number_input("Nombre de wagons initiaux", min_value=10, max_value=5000, value=500, step=10)

        # 3. Choix du mode d'exécution
        st.sidebar.subheader("3. Mode d'Exécution")
        mode_choice = st.sidebar.radio(
            "Choisissez le mode :",
            ("Simulation Simple", "Optimisation (Montée)"),
            horizontal=True,
            label_visibility="collapsed"
        )
        
        # 4. Choix de l'heuristique
        st.sidebar.subheader("4. Choix de l'Heuristique")
        heuristique_choice = st.sidebar.radio("Heuristique", ("H1", "H2"), horizontal=True, key="heuristique_choice")
        
        # 5. Configuration des ordres (le titre s'adapte au mode)
        if mode_choice == "Simulation Simple":
            st.sidebar.subheader("5. Stratégie de Priorisation")
            section_title = "Critères de tri fixes"
        else: # Mode Optimisation
            st.sidebar.subheader("5. Point de Départ de l'Optimisation")
            section_title = "Ordres de départ pour la montée"
            max_iter = st.sidebar.number_input("Nombre max d'itérations", min_value=1, max_value=100, value=10, help="Nombre de cycles d'amélioration que l'algorithme de montée tentera.")

        # Menus déroulants uniformes pour H1 et H2
        sort_options = {
            "Demande annuelle (décroissant)": ('annual_demand_tons', False),
            "QMIN (décroissant)": ('q_min_initial_target_tons', False),
            "Demande annuelle (croissant)": ('annual_demand_tons', True),
            "QMIN (croissant)": ('q_min_initial_target_tons', True),
        }

        st.sidebar.write(f"**{section_title}**")
        qmin_sort_choice = st.sidebar.selectbox("Ordre pour livraisons QMIN:", sort_options.keys(), key="qmin_order")
        phase2_sort_choice = st.sidebar.selectbox("Ordre pour livraisons Phase 2 (rentables):", sort_options.keys(), key="phase2_order")
        
        start_qmin_config = sort_options[qmin_sort_choice]
        start_phase2_config = sort_options[phase2_sort_choice]
        
        # Bouton pour lancer l'exécution
        if st.sidebar.button("🚀 Lancer l'Exécution", use_container_width=True):
            st.session_state.log_optim = "" # Réinitialiser le journal
            final_sim_results = None
            
            with st.spinner("Exécution en cours... Cela peut prendre plusieurs minutes pour une optimisation."):
                
                # --- LOGIQUE D'APPEL ---
                
                # Cas 1: Simulation Simple
                if mode_choice == "Simulation Simple":
                    if heuristique_choice == "H1":
                        final_sim_results = sim.run_simulation_h1(
                            relations_df, origins_df, destinations_df,
                            qmin_common_config=start_qmin_config,
                            phase2_config=start_phase2_config,
                            num_initial_wagons_param=num_wagons, silent_mode=True
                        )
                    else: # H2
                        qmin_list = generate_list_from_config(destinations_df, start_qmin_config)
                        phase2_list = generate_list_from_config(destinations_df, start_phase2_config)
                        final_sim_results = sim.run_simulation_h2(
                            relations_df, origins_df, destinations_df,
                            qmin_user_priority_order=qmin_list,
                            standard_shipment_dest_priority_order=phase2_list,
                            num_initial_wagons_param=num_wagons, silent_mode=True
                        )
                
                # Cas 2: Optimisation (Montée)
                else:
                    st.session_state.log_optim += f"Lancement de l'optimisation {heuristique_choice} avec {max_iter} itérations...\n"
                    st.session_state.log_optim += f"Nombre de wagons: {num_wagons}\n"
                    
                    start_qmin_list = generate_list_from_config(destinations_df, start_qmin_config)
                    start_phase2_list = generate_list_from_config(destinations_df, start_phase2_config)
                    st.session_state.log_optim += f"Ordre de départ QMIN: {start_qmin_list}\n"
                    st.session_state.log_optim += f"Ordre de départ Phase 2: {start_phase2_list}\n\n"
                    
                    # Capture de la sortie console pour l'afficher dans l'interface
                    old_stdout = sys.stdout
                    sys.stdout = captured_output = StringIO()

                    if heuristique_choice == 'H1':
                        start_qmin_h1_config = ('custom_order', start_qmin_list)
                        start_phase2_h1_config = ('custom_order', start_phase2_list)
                        # Appel de votre fonction d'optimisation
                        best_qmin_cfg, _, best_phase2_cfg = sim.hill_climbing_maximizer_h1(
                            relations_df, origins_df, destinations_df,
                            start_qmin_h1_config, start_phase2_h1_config, num_wagons, max_iter
                        )
                        # On relance une simulation finale avec les meilleurs ordres trouvés
                        final_sim_results = sim.run_simulation_h1(
                            relations_df, origins_df, destinations_df,
                            best_qmin_cfg, best_phase2_cfg, num_wagons, silent_mode=True
                        )
                    else: # H2
                        # Appel de votre fonction d'optimisation
                        best_qmin_order, best_phase2_order = sim.hill_climbing_maximizer_h2(
                            relations_df, origins_df, destinations_df,
                            start_qmin_list, start_phase2_list, num_wagons, max_iter
                        )
                        # On relance une simulation finale avec les meilleurs ordres trouvés
                        final_sim_results = sim.run_simulation_h2(
                            relations_df, origins_df, destinations_df,
                            best_qmin_order, best_phase2_order, num_wagons, silent_mode=True
                        )

                    sys.stdout = old_stdout # Restauration de la sortie console
                    st.session_state.log_optim += captured_output.getvalue()

            st.session_state.results = final_sim_results
            st.session_state.initial_data = (origins_df.copy(), destinations_df.copy())
            st.experimental_rerun() # Rafraîchit l'interface pour afficher les résultats
else:
    st.info("👋 Bienvenue ! Veuillez téléverser les 3 fichiers CSV dans la barre latérale pour commencer.")

# --- Affichage des Résultats dans la page principale ---
if st.session_state.results:
    res = st.session_state.results
    st.header("📊 Résultats de l'Exécution")
    
    # Affichage du journal d'optimisation s'il existe
    if st.session_state.log_optim:
        with st.expander("Voir le journal de l'optimisation", expanded=True):
            st.code(st.session_state.log_optim, language="bash")

    # Indicateurs de performance clés
    col1, col2, col3 = st.columns(3)
    col1.metric("Profit Final (Tonnes * km)", f"{res.get('profit', 0):,.0f}".replace(',', ' '))
    col2.metric("Jours de simulation", f"{res.get('days_taken_simulation_loop', 'N/A')}")
    col3.metric("Demande satisfaite ?", "✅ Oui" if res.get('all_demand_met', False) else "❌ Non")
    
    # Bouton de téléchargement Excel
    initial_orig, initial_dest = st.session_state.initial_data
    excel_data = create_excel_download(res, initial_orig, initial_dest)
    st.download_button(
        label="📥 Télécharger le rapport complet (Excel)",
        data=excel_data,
        file_name=f"resultats_simulation.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )

    # Onglets pour les résultats détaillés
    tab1, tab2, tab3, tab4 = st.tabs(["Expéditions", "Récapitulatif Destinations", "Récapitulatif Origines", "Suivi des Wagons"])

    with tab1:
        st.subheader("Détail des Expéditions")
        shipments_df = res.get('shipments_df')
        if shipments_df is not None and not shipments_df.empty:
            st.dataframe(shipments_df.style.format(precision=2))
        else:
            st.info("Aucune expédition n'a été réalisée.")

    with tab2:
        st.subheader("État Final par Destination")
        final_dest_df = res.get('final_destinations_df')
        if final_dest_df is not None:
            st.dataframe(final_dest_df.style.format(precision=2))
        else:
            st.warning("Données de destination finales non disponibles.")

    with tab3:
        st.subheader("État Final par Origine")
        final_orig_df = res.get('final_origins_df')
        if final_orig_df is not None:
            st.dataframe(final_orig_df.style.format(precision=2))
        else:
            st.warning("Données d'origine finales non disponibles.")
            
    with tab4:
        st.subheader("Suivi Quotidien des Wagons")
        tracking_vars = res.get('final_tracking_vars')
        if tracking_vars:
            wagon_log_df = pd.DataFrame(tracking_vars.get('daily_wagon_log', []))
            if not wagon_log_df.empty:
                st.line_chart(wagon_log_df.set_index('day'), y=['available_start', 'in_transit_end'])
                with st.expander("Voir les données détaillées du suivi des wagons"):
                    st.dataframe(wagon_log_df)
            else:
                st.info("Aucun suivi de wagon n'a été enregistré.")
