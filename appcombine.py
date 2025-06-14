# app.py
import streamlit as st
import pandas as pd
from io import BytesIO, StringIO
import sys
import traceback # Important pour afficher les erreurs détaillées

# --- Configuration de la Page ---
st.set_page_config(
    layout="wide",
    page_title="Simulateur & Optimiseur Logistique",
    page_icon="🚢"
)

# --- Importation du module de logique métier ---
# On s'assure que le fichier contenant la logique (simulation, optimisation) est présent.
try:
    import combainaisonexceldescente as sim
except ImportError:
    st.error("ERREUR CRITIQUE: Le fichier 'combainaisonexceldescente.py' est introuvable.")
    st.info("Veuillez vous assurer que ce fichier se trouve dans le même dossier que 'app.py'.")
    st.stop()

# --- Fonctions Utilitaires ---

@st.cache_data # Mise en cache pour ne pas recharger les fichiers à chaque action
def load_and_clean_data(relations_file, origins_file, destinations_file):
    """Charge et nettoie les données à partir des fichiers CSV téléversés."""
    try:
        def clean_numeric_column(series):
            # Fonction pour nettoyer les colonnes numériques (enlève les espaces et remplace la virgule)
            return pd.to_numeric(series.astype(str).str.replace('\u202f', '', regex=False).str.replace(',', '.', regex=False).str.strip(), errors='coerce')

        relations_df = pd.read_csv(relations_file, dtype=str)
        relations_df['origin'] = relations_df['origin'].str.strip()
        relations_df['destination'] = relations_df['destination'].str.strip()
        relations_df['distance_km'] = clean_numeric_column(relations_df['distance_km'])
        relations_df['profitability'] = clean_numeric_column(relations_df['profitability'])

        origins_df_raw = pd.read_csv(origins_file, dtype=str)
        origins_df_raw['id'] = origins_df_raw['id'].str.strip()
        origins_df_raw['daily_loading_capacity_tons'] = clean_numeric_column(origins_df_raw['daily_loading_capacity_tons'])
        origins_df_raw['initial_available_product_tons'] = clean_numeric_column(origins_df_raw['initial_available_product_tons'])
        origins_df = origins_df_raw.set_index('id')

        destinations_df_raw = pd.read_csv(destinations_file, dtype=str)
        destinations_df_raw['id'] = destinations_df_raw['id'].str.strip()
        destinations_df_raw['daily_unloading_capacity_tons'] = clean_numeric_column(destinations_df_raw['daily_unloading_capacity_tons'])
        destinations_df_raw['annual_demand_tons'] = clean_numeric_column(destinations_df_raw['annual_demand_tons'])
        destinations_df = destinations_df_raw.set_index('id')

        return relations_df, origins_df, destinations_df
    except Exception as e:
        st.error(f"Erreur lors de la lecture ou du nettoyage des fichiers CSV : {e}")
        return None, None, None

def generate_list_from_config(df, config_tuple):
    """Génère une liste d'identifiants triée selon une configuration."""
    sort_column, ascending_order = config_tuple
    df_copy = df.copy()
    # Calcule la colonne 'q_min' si elle n'existe pas, pour le tri
    if 'q_min_initial_target_tons' not in df_copy.columns and 'annual_demand_tons' in df_copy.columns:
        df_copy['q_min_initial_target_tons'] = df_copy['annual_demand_tons'] * 0.20
    
    if sort_column not in df_copy.columns:
        st.warning(f"La colonne de tri '{sort_column}' n'a pas été trouvée. Utilisation de l'ordre par défaut.")
        return df_copy.index.tolist()
        
    return df_copy.sort_values(by=sort_column, ascending=ascending_order).index.tolist()

def create_excel_download_link(sim_results, origins_initial_df, destinations_initial_df):
    """Crée un fichier Excel en mémoire pour le téléchargement."""
    output = BytesIO()
    # Utilise la fonction d'écriture Excel du module de simulation
    sim.ecrire_resultats_excel(
        output,
        "resultats_simulation",
        sim_results,
        origins_initial_df,
        destinations_initial_df
    )
    return output.getvalue()

# --- Initialisation de l'état de la session ---
if 'results' not in st.session_state:
    st.session_state.results = None
if 'log_output' not in st.session_state:
    st.session_state.log_output = ""
if 'initial_data' not in st.session_state:
    st.session_state.initial_data = None

# ==============================================================================
# --- INTERFACE UTILISATEUR (UI) ---
# ==============================================================================

st.title("🚢 Simulateur & Optimiseur Logistique")

# --- BARRE LATÉRALE DE CONFIGURATION ---
with st.sidebar:
    st.header("⚙️ Configuration")

    st.subheader("1. Fichiers de Données (.csv)")
    relations_file = st.file_uploader("Relations (Origine-Destination)", type="csv")
    origins_file = st.file_uploader("Fichier des Origines", type="csv")
    destinations_file = st.file_uploader("Fichier des Destinations", type="csv")

    # Si les fichiers sont chargés, on affiche le reste des options
    if relations_file and origins_file and destinations_file:
        relations_df, origins_df, destinations_df = load_and_clean_data(relations_file, origins_file, destinations_file)
        
        if relations_df is not None: # Vérifie que le chargement s'est bien passé
            st.success("✅ Fichiers chargés avec succès.")
            
            st.subheader("2. Paramètres Globaux")
            num_wagons = st.number_input("Nombre de wagons initiaux", min_value=10, max_value=5000, value=500, step=10)
            
            st.subheader("3. Mode d'Exécution")
            mode_choice = st.radio("Choisissez le mode :", ("Simulation Simple", "Optimisation (Montée)"), horizontal=True)

            st.subheader("4. Choix de l'Heuristique")
            heuristique_choice = st.radio("Heuristique utilisée :", ("H1", "H2"), horizontal=True, key="heuristique_choice")
            
            # Options de tri pour les listes de priorité
            sort_options = {
                "Demande Annuelle (Décroissant)": ('annual_demand_tons', False),
                "QMIN Cible (Décroissant)": ('q_min_initial_target_tons', False),
                "Demande Annuelle (Croissant)": ('annual_demand_tons', True),
                "QMIN Cible (Croissant)": ('q_min_initial_target_tons', True),
            }

            if mode_choice == "Simulation Simple":
                st.subheader("5. Stratégie de Priorisation")
                with st.expander("Définir les ordres de priorité", expanded=True):
                    qmin_sort_choice = st.selectbox("Ordre de priorité pour QMIN:", sort_options.keys(), key="qmin_order_sim")
                    phase2_sort_choice = st.selectbox("Ordre de priorité pour Phase 2:", sort_options.keys(), key="phase2_order_sim")
            
            else: # Mode Optimisation
                st.subheader("5. Configuration de l'Optimisation")
                max_iter = st.number_input("Nombre max d'itérations pour la montée :", min_value=1, max_value=100, value=10)
                with st.expander("Définir le point de départ de l'optimisation", expanded=True):
                    qmin_sort_choice = st.selectbox("Ordre de départ pour QMIN:", sort_options.keys(), key="qmin_order_opt")
                    phase2_sort_choice = st.selectbox("Ordre de départ pour Phase 2:", sort_options.keys(), key="phase2_order_opt")

            # Bouton pour lancer l'exécution
            if st.button("🚀 Lancer l'Exécution", use_container_width=True, type="primary"):
                # Récupérer les configurations de tri choisies
                start_qmin_config = sort_options[qmin_sort_choice]
                start_phase2_config = sort_options[phase2_sort_choice]
                
                # Sauvegarder les données initiales pour la comparaison
                st.session_state.initial_data = (origins_df.copy(), destinations_df.copy())
                st.session_state.log_output = "" # Réinitialiser le log

                # --- BLOC D'EXÉCUTION PRINCIPAL ---
                with st.spinner("Exécution en cours... Veuillez patienter."):
                    try:
                        # Capture de la sortie console (pour le log de la montée)
                        old_stdout = sys.stdout
                        sys.stdout = captured_output = StringIO()

                        if mode_choice == "Simulation Simple":
                            st.session_state.log_output = "Lancement d'une simulation simple...\n"
                            if heuristique_choice == "H1":
                                results = sim.run_simulation_h1(
                                    relations_df, origins_df, destinations_df,
                                    qmin_common_config=start_qmin_config,
                                    phase2_config=start_phase2_config,
                                    num_initial_wagons_param=num_wagons,
                                    silent_mode=True
                                )
                            else: # H2
                                qmin_list = generate_list_from_config(destinations_df, start_qmin_config)
                                phase2_list = generate_list_from_config(destinations_df, start_phase2_config)
                                results = sim.run_simulation_h2(
                                    relations_df, origins_df, destinations_df,
                                    qmin_user_priority_order=qmin_list,
                                    standard_shipment_dest_priority_order=phase2_list,
                                    num_initial_wagons_param=num_wagons,
                                    silent_mode=True
                                )
                        
                        else: # Mode Optimisation
                            st.session_state.log_output = f"Lancement de l'optimisation ({heuristique_choice}) avec max {max_iter} itérations...\n\n"
                            start_qmin_list = generate_list_from_config(destinations_df, start_qmin_config)
                            start_phase2_list = generate_list_from_config(destinations_df, start_phase2_config)

                            if heuristique_choice == 'H1':
                                # Pour H1, l'optimiseur a besoin de la configuration, pas seulement de la liste
                                start_qmin_h1_config = ('custom_order', start_qmin_list)
                                start_phase2_h1_config = ('custom_order', start_phase2_list)
                                best_qmin_cfg, _, best_phase2_cfg = sim.hill_climbing_maximizer_h1(
                                    relations_df, origins_df, destinations_df,
                                    start_qmin_h1_config, start_phase2_h1_config,
                                    num_wagons, max_iter
                                )
                                # Lancer la simulation finale avec les meilleurs ordres trouvés
                                results = sim.run_simulation_h1(
                                    relations_df, origins_df, destinations_df,
                                    best_qmin_cfg, best_phase2_cfg, num_wagons, silent_mode=True
                                )
                            else: # H2
                                best_qmin_order, best_phase2_order = sim.hill_climbing_maximizer_h2(
                                    relations_df, origins_df, destinations_df,
                                    start_qmin_list, start_phase2_list,
                                    num_wagons, max_iter
                                )
                                # Lancer la simulation finale avec les meilleurs ordres trouvés
                                results = sim.run_simulation_h2(
                                    relations_df, origins_df, destinations_df,
                                    best_qmin_order, best_phase2_order, num_wagons, silent_mode=True
                                )

                        # Restaurer la sortie standard et sauvegarder le log
                        sys.stdout = old_stdout
                        st.session_state.log_output += captured_output.getvalue()
                        st.session_state.results = results
                        
                    except Exception as e:
                        # ** GESTION D'ERREUR **
                        # Si quelque chose ne va pas dans le bloc 'try', on l'affiche ici.
                        sys.stdout = old_stdout # S'assurer de restaurer la sortie
                        st.error(f"❌ Une erreur est survenue pendant l'exécution :")
                        st.error(str(e))
                        st.code(traceback.format_exc()) # Affiche les détails techniques de l'erreur
                        st.session_state.results = None # Empêche d'afficher d'anciens résultats
                
                st.rerun() # Rafraîchit la page pour afficher les résultats

# Affiche un message d'accueil si aucun fichier n'est chargé
if not (relations_file and origins_file and destinations_file):
    st.info("👋 Bienvenue ! Veuillez téléverser les 3 fichiers CSV dans la barre latérale pour commencer.")


# ==============================================================================
# --- AFFICHAGE DES RÉSULTATS ---
# ==============================================================================

if st.session_state.results:
    res = st.session_state.results
    st.header("📊 Résultats de l'Exécution")

    # Afficher le journal (log) si il existe
    if st.session_state.log_output and st.session_state.log_output.strip():
        with st.expander("Voir le journal de l'exécution", expanded=False):
            st.code(st.session_state.log_output, language="bash")

    # Indicateurs clés de performance (KPIs)
    col1, col2, col3 = st.columns(3)
    col1.metric("Profit Final (Tonnes * km)", f"{res.get('profit', 0):,.0f}".replace(',', ' '))
    col2.metric("Jours de simulation", f"{res.get('days_taken_simulation_loop', 'N/A')}")
    col3.metric("Demande satisfaite ?", "✅ Oui" if res.get('all_demand_met', False) else "❌ Non")
    
    # Bouton de téléchargement Excel
    if st.session_state.initial_data:
        initial_orig, initial_dest = st.session_state.initial_data
        excel_data = create_excel_download_link(res, initial_orig, initial_dest)
        st.download_button(
            label="📥 Télécharger le rapport complet (Excel)",
            data=excel_data,
            file_name="resultats_simulation.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

    # Récupération des dataframes de résultats pour les onglets
    shipments_df = res.get('shipments_df')
    final_dest_df = res.get('final_destinations_df')
    final_orig_df = res.get('final_origins_df')
    tracking_vars = res.get('final_tracking_vars')

    # Onglets pour organiser les résultats
    tab_graph, tab_transport, tab_dest, tab_orig, tab_wagon = st.tabs([
        "📈 Graphiques & KPIs", "🚚 Détail des Transports", "🎯 Récap. Destinations", 
        "🏭 Récap. Origines", "🛤️ Suivi des Wagons"
    ])

    with tab_graph:
        st.subheader("Analyse Visuelle")
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
                if final_dest_df is not None and 'annual_demand_tons' in final_dest_df.columns and 'delivered_so_far_tons' in final_dest_df.columns:
                    recap_df = final_dest_df.copy()
                    # Éviter la division par zéro
                    recap_df['satisfaction_rate'] = recap_df.apply(
                        lambda row: (row['delivered_so_far_tons'] / row['annual_demand_tons'] * 100) if row['annual_demand_tons'] > 0 else 0,
                        axis=1
                    ).fillna(0)
                    st.bar_chart(recap_df, y='satisfaction_rate')
                else:
                    st.warning("Données de destination manquantes pour le graphique de satisfaction.")
            
            st.write("**Flux d'expédition par jour (en tonnes)**")
            tons_per_day = shipments_df.groupby('ship_day')['quantity_tons'].sum()
            st.line_chart(tons_per_day)
        else:
            st.info("Aucune expédition n'a été réalisée. Impossible de générer les graphiques.")

    with tab_transport:
        st.subheader("Tableau de Transport (Détail des Expéditions)")
        if shipments_df is not None:
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
        if tracking_vars:
            wagon_log_df = pd.DataFrame(tracking_vars.get('daily_wagon_log', []))
            if not wagon_log_df.empty:
                st.line_chart(wagon_log_df.set_index('day'), y=['available_start', 'in_transit_end'], color=["#FFBF00", "#008ECC"])
                with st.expander("Voir les données détaillées du suivi"):
                    st.dataframe(wagon_log_df)
            else:
                st.info("Aucune donnée de suivi des wagons n'a été enregistrée.")
        else:
            st.info("Le suivi des wagons n'était pas activé ou n'a retourné aucune donnée.")

        

           
                    
       
