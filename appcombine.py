# app.py
import streamlit as st
import pandas as pd
from io import BytesIO
import traceback # Important pour afficher les erreurs détaillées
import numpy as np # Importation de numpy pour gérer l'infini

# --- Configuration de la Page ---
st.set_page_config(
    layout="wide",
    page_title="Simulateur Logistique",
    page_icon="🚢"
)

# --- Importation du module de logique métier ---
try:
    # Assurez-vous que votre fichier de logique s'appelle bien comme ça
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
        st.error(f"Erreur lors de la lecture des fichiers CSV : {e}")
        return None, None, None

def generate_list_from_config(df, config_tuple):
    """Génère une liste d'identifiants triée selon une configuration."""
    sort_column, ascending_order = config_tuple
    df_copy = df.copy()
    if 'q_min_initial_target_tons' not in df_copy.columns and 'annual_demand_tons' in df_copy.columns:
        df_copy['q_min_initial_target_tons'] = df_copy['annual_demand_tons'] * 0.20
    
    if sort_column not in df_copy.columns:
        st.warning(f"La colonne de tri '{sort_column}' n'a pas été trouvée. Utilisation de l'ordre par défaut.")
        return df_copy.index.tolist()
        
    return df_copy.sort_values(by=sort_column, ascending=ascending_order).index.tolist()

def create_excel_download_link(sim_results, origins_initial_df, destinations_initial_df):
    """Crée un fichier Excel en mémoire pour le téléchargement."""
    output = BytesIO()
    sim.ecrire_resultats_excel(output, "resultats_simulation", sim_results, origins_initial_df, destinations_initial_df)
    return output.getvalue()

# --- Initialisation de l'état de la session ---
if 'results' not in st.session_state:
    st.session_state.results = None
if 'initial_data' not in st.session_state:
    st.session_state.initial_data = None

# ==============================================================================
# --- INTERFACE UTILISATEUR (UI) ---
# ==============================================================================

st.title("🚢 Simulateur Logistique")

# --- BARRE LATÉRALE DE CONFIGURATION ---
with st.sidebar:
    st.header("⚙️ Configuration de la Simulation")

    st.subheader("1. Fichiers de Données (.csv)")
    relations_file = st.file_uploader("Relations (Origine-Destination)", type="csv")
    origins_file = st.file_uploader("Fichier des Origines", type="csv")
    destinations_file = st.file_uploader("Fichier des Destinations", type="csv")

    if relations_file and origins_file and destinations_file:
        relations_df_raw, origins_df_raw, destinations_df_raw = load_and_clean_data(relations_file, origins_file, destinations_file)
        
        # Copie des dataframes pour éviter la corruption du cache
        relations_df = relations_df_raw.copy()
        origins_df = origins_df_raw.copy()
        destinations_df = destinations_df_raw.copy()
        
        if relations_df is not None:
            st.success("✅ Fichiers chargés.")
            
            st.subheader("2. Paramètres Globaux")
            num_wagons = st.number_input("Nombre de wagons initiaux", min_value=10, max_value=5000, value=500, step=10)
            
            st.subheader("3. Choix de l'Heuristique")
            heuristique_choice = st.radio("Heuristique à utiliser :", ("H1", "H2"), horizontal=True)
            
            st.subheader("4. Stratégie de Priorisation")
            sort_options = {
                "Demande Annuelle (Décroissant)": ('annual_demand_tons', False),
                "QMIN Cible (Décroissant)": ('q_min_initial_target_tons', False),
                "Demande Annuelle (Croissant)": ('annual_demand_tons', True),
                "QMIN Cible (Croissant)": ('q_min_initial_target_tons', True),
            }
            
            qmin_sort_choice = st.selectbox("Ordre de priorité pour QMIN (Phase 1):", sort_options.keys(), key="qmin_order")
            phase2_sort_choice = st.selectbox("Ordre de priorité pour expéditions (Phase 2):", sort_options.keys(), key="phase2_order")
            
            if st.button("🚀 Lancer la Simulation", use_container_width=True, type="primary"):
                qmin_config = sort_options[qmin_sort_choice]
                phase2_config = sort_options[phase2_sort_choice]
                
                # Sauvegarde des données initiales PURES avant toute modification
                st.session_state.initial_data = (origins_df.copy(), destinations_df.copy())

                with st.spinner("Simulation en cours..."):
                    try:
                        if heuristique_choice == "H1":
                            results = sim.run_simulation_h1(
                                relations_df, origins_df.copy(), destinations_df.copy(),
                                qmin_common_config=qmin_config,
                                phase2_config=phase2_config,
                                num_initial_wagons_param=num_wagons,
                                silent_mode=True
                            )
                        else: # Heuristique H2
                            qmin_list = generate_list_from_config(destinations_df, qmin_config)
                            phase2_list = generate_list_from_config(destinations_df, phase2_config)
                            results = sim.run_simulation_h2(
                                relations_df, origins_df.copy(), destinations_df.copy(),
                                qmin_user_priority_order=qmin_list,
                                standard_shipment_dest_priority_order=phase2_list,
                                num_initial_wagons_param=num_wagons,
                                silent_mode=True
                            )
                        
                        st.session_state.results = results
                        
                    except Exception as e:
                        st.error(f"❌ Une erreur est survenue pendant la simulation :")
                        st.error(str(e))
                        st.code(traceback.format_exc())
                        st.session_state.results = None
                
                st.rerun()

if not (relations_file and origins_file and destinations_file):
    st.info("👋 Bienvenue ! Veuillez téléverser vos 3 fichiers CSV dans la barre latérale pour commencer.")

# ==============================================================================
# --- AFFICHAGE DES RÉSULTATS ---
# ==============================================================================

if st.session_state.results:
    res = st.session_state.results
    st.header("📊 Résultats de la Simulation")

    # KPIs
    col1, col2, col3 = st.columns(3)
    col1.metric("Profit Final (Tonnes * km)", f"{res.get('profit', 0):,.0f}".replace(',', ' '))
    col2.metric("Jours de simulation", f"{res.get('days_taken_simulation_loop', 'N/A')}")
    col3.metric("Demande satisfaite ?", "✅ Oui" if res.get('all_demand_met', False) else "❌ Non")
    
    st.divider()

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

    shipments_df = res.get('shipments_df')
    final_dest_df = res.get('final_destinations_df')
    final_orig_df = res.get('final_origins_df')
    tracking_vars = res.get('final_tracking_vars')

    tab_graph, tab_transport, tab_dest, tab_orig, tab_wagon = st.tabs([
        "📈 Graphiques", "🚚 Détail des Transports", "🎯 Destinations", "🏭 Origines", "🛤️ Suivi Wagons"
    ])

    with tab_graph:
        st.subheader("Analyse Visuelle")
        if shipments_df is not None and not shipments_df.empty:
            # ... (code de l'onglet graphiques inchangé) ...
            col1_graph, col2_graph = st.columns(2)
            with col1_graph:
                st.write("**Quantité livrée par destination**")
                tons_per_dest = shipments_df.groupby('destination')['quantity_tons'].sum().sort_values(ascending=False)
                st.bar_chart(tons_per_dest)
                st.write("**Quantité expédiée par origine**")
                tons_per_origin = shipments_df.groupby('origin')['quantity_tons'].sum().sort_values(ascending=False)
                st.bar_chart(tons_per_origin)
            with col2_graph:
                st.write("**Taux de satisfaction de la demande (%)**")
                if final_dest_df is not None and all(c in final_dest_df.columns for c in ['annual_demand_tons', 'delivered_so_far_tons']):
                    recap_df = final_dest_df.copy()
                    recap_df['satisfaction_rate'] = recap_df.apply(lambda row: (row['delivered_so_far_tons'] / row['annual_demand_tons'] * 100) if row['annual_demand_tons'] > 0 else 0, axis=1).fillna(0)
                    st.bar_chart(recap_df, y='satisfaction_rate')
                else:
                    st.warning("Données manquantes pour le graphique de satisfaction.")
            st.write("**Flux d'expédition par jour (en tonnes)**")
            tons_per_day = shipments_df.groupby('ship_day')['quantity_tons'].sum()
            st.line_chart(tons_per_day)
        else:
            st.info("Aucune expédition n'a été réalisée.")


    with tab_transport:
        st.subheader("Détail de toutes les Expéditions")
        if shipments_df is not None:
            st.dataframe(shipments_df.style.format(precision=2))

    with tab_dest:
        st.subheader("État Final par Destination")
        if final_dest_df is not None:
            st.dataframe(final_dest_df.style.format(precision=2))

    # --- BLOC "ORIGINES" MODIFIÉ AVEC DÉBOGAGE INTÉGRÉ ---
    with tab_orig:
        st.subheader("État Final par Origine")
        
        if final_orig_df is not None and st.session_state.initial_data:
            initial_orig_df, _ = st.session_state.initial_data
            origins_display_df = final_orig_df.copy()

            # --- PARAMÈTRES À VÉRIFIER ---
            # Nom de la colonne du stock DANS LE FICHIER INITIAL
            col_stock_initial = 'initial_available_product_tons'
            
            # Nom de la colonne du stock DANS LE FICHIER FINAL (retourné par la simulation)
            # 💡 HYPOTHÈSE : C'est 'initial_available_product_tons'. Si ça ne marche pas,
            #    l'application affichera la liste des colonnes disponibles et vous pourrez
            #    corriger le nom ici.
            col_stock_final = 'initial_available_product_tons' 
            # --- FIN DES PARAMÈTRES ---

            # On vérifie que les colonnes existent avant de continuer
            if col_stock_initial in initial_orig_df.columns and col_stock_final in origins_display_df.columns:
                
                origins_display_df['stock_initial_t'] = initial_orig_df[col_stock_initial]
                origins_display_df['stock_final_t'] = origins_display_df[col_stock_final]
                origins_display_df['stock_utilise_t'] = origins_display_df['stock_initial_t'] - origins_display_df['stock_final_t']

                origins_display_df['utilisation_stock_%'] = origins_display_df.apply(
                    lambda row: (row['stock_utilise_t'] / row['stock_initial_t'] * 100) if row['stock_initial_t'] > 0 else 0,
                    axis=1
                )
                
                days_sim = res.get('days_taken_simulation_loop')
                if shipments_df is not None and not shipments_df.empty and days_sim is not None and days_sim > 0:
                    daily_flow_per_origin = shipments_df.groupby('origin')['quantity_tons'].sum() / days_sim
                    origins_display_df['debit_moyen_jour'] = origins_display_df.index.map(daily_flow_per_origin).fillna(0)
                    origins_display_df['autonomie_restante_j'] = origins_display_df.apply(
                        lambda row: row['stock_final_t'] / row['debit_moyen_jour'] if row['debit_moyen_jour'] > 0 else np.inf,
                        axis=1
                    )
                    origins_display_df = origins_display_df.drop(columns=['debit_moyen_jour'])
                else:
                    origins_display_df['autonomie_restante_j'] = np.nan

                cols_to_display = [
                    'stock_initial_t', 'stock_final_t', 'stock_utilise_t', 'utilisation_stock_%',
                    'autonomie_restante_j', 'daily_loading_capacity_tons'
                ]
                # On ne garde que les colonnes existantes et on ajoute les autres
                final_cols_order = [c for c in cols_to_display if c in origins_display_df.columns]
                other_cols = [c for c in origins_display_df.columns if c not in final_cols_order]
                
                st.dataframe(origins_display_df[final_cols_order + other_cols].style.format({
                    'stock_initial_t': '{:,.0f}',
                    'stock_final_t': '{:,.0f}',
                    'stock_utilise_t': '{:,.0f}',
                    'daily_loading_capacity_tons': '{:,.0f}',
                    'utilisation_stock_%': '{:.1f}%',
                    'autonomie_restante_j': '{:.1f}'
                }, na_rep="N/A").set_properties(**{'text-align': 'right'}))

            else:
                # --- GUIDE DE DÉBOGAGE ---
                st.error("❌ ERREUR DE CONFIGURATION DES COLONNES", icon="⚙️")
                st.write(
                    "Le calcul du stock utilisé a échoué car une colonne n'a pas été trouvée. "
                    "Cela signifie que le nom de la colonne du stock final dans le code ne correspond pas "
                    "à celui retourné par votre simulation."
                )
                st.info(f"**Action à faire :**\n"
                        f"1. Regardez la liste des 'Colonnes disponibles' ci-dessous.\n"
                        f"2. Identifiez le vrai nom de la colonne qui contient le stock final.\n"
                        f"3. Dans le code `app.py`, trouvez la ligne `col_stock_final = ...` (dans l'onglet 'Origines') "
                        f"et remplacez la valeur par le nom correct que vous avez trouvé.", icon="💡")

                st.subheader("Données pour le débogage :")
                st.write(f"**Nom de colonne de stock initial cherché :** `{col_stock_initial}` (Présent: {col_stock_initial in initial_orig_df.columns})")
                st.write(f"**Nom de colonne de stock final cherché :** `{col_stock_final}` (Présent: {col_stock_final in origins_display_df.columns})")
                
                st.subheader("Colonnes disponibles dans le dataframe final (`final_orig_df`):")
                st.code(final_orig_df.columns.tolist())
                st.subheader("Aperçu des données finales :")
                st.dataframe(final_orig_df)

        else:
            st.info("Les données sur l'état final des origines ne sont pas disponibles.")
            
    with tab_wagon:
        st.subheader("Suivi Quotidien des Wagons")
        if tracking_vars and 'daily_wagon_log' in tracking_vars:
            wagon_log_df = pd.DataFrame(tracking_vars['daily_wagon_log'])
            if not wagon_log_df.empty:
                st.line_chart(wagon_log_df.set_index('day'), y=['available_start', 'in_transit_end'])
                with st.expander("Voir les données détaillées"):
                    st.dataframe(wagon_log_df)
            else:
                st.info("Aucune donnée de suivi des wagons n'a été enregistrée.")
        else:
            st.info("Le suivi des wagons n'était pas activé ou n'a retourné aucune donnée.")
   


    

             
   
             
         
       
