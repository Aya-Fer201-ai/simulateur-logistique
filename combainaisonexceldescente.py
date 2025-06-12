import pandas as pd
import math
import itertools
# import copy
# import random

# --- MODIFICATION: Utilisation de chemins absolus pour la robustesse ---
# Assurez-vous que ce chemin est correct pour votre ordinateur
CHEMIN_DU_DOSSIER_DE_DONNEES = r"C:\Users\mounito\Documents\RO2MIR\memoirepfe\codes"

# --- Configuration Fichiers CSV d'Entrée ---
FICHIER_CSV_RELATIONS = f"{CHEMIN_DU_DOSSIER_DE_DONNEES}\\input_relations.csv"
FICHIER_CSV_ORIGINS = f"{CHEMIN_DU_DOSSIER_DE_DONNEES}\\input_origines.csv"
FICHIER_CSV_DESTINATIONS = f"{CHEMIN_DU_DOSSIER_DE_DONNEES}\\input_destination.csv"

# --- Configuration Fichier Excel de Sortie ---
FICHIER_EXCEL_SORTIE = f"{CHEMIN_DU_DOSSIER_DE_DONNEES}\\pfe_simulation_results.xlsx"
NOM_FEUILLE_EXCEL_RESULTATS = "resultats"

# --- Configuration Globale ---
WAGON_CAPACITY_TONS = 50
MIN_WAGON_UTILIZATION_PERCENT = 0.30
MIN_SHIPMENT_FOR_ONE_WAGON_TONS = WAGON_CAPACITY_TONS * MIN_WAGON_UTILIZATION_PERCENT
MAX_SIMULATION_DAYS = 260
KM_PER_DAY_FOR_WAGON_RETURN = 200
EPSILON = 1e-9

# --- 1. Charger et Nettoyer les données depuis CSV ---
def load_data_csv(fichier_relations_path, fichier_origines_path, fichier_destinations_path):
    print(f"\n--- Chargement et Nettoyage des Données depuis Fichiers CSV ---")
    try:
        def clean_numeric_column(series):
            return series.astype(str).str.replace('\u202f', '', regex=False).str.replace(',', '.', regex=False).str.strip()

        # --- Feuille Relations ---
        print(f"Lecture du fichier relations : {fichier_relations_path}")
        relations_df = pd.read_csv(fichier_relations_path, dtype=str)
        # CORRECTION : Nettoyer les noms dans les relations
        relations_df['origin'] = relations_df['origin'].str.strip()
        relations_df['destination'] = relations_df['destination'].str.strip()
        relations_df['distance_km'] = clean_numeric_column(relations_df['distance_km']).astype(float)
        relations_df['profitability'] = clean_numeric_column(relations_df['profitability']).astype(int)
        print(f"  - Fichier '{fichier_relations_path}' ({len(relations_df)} lignes) lu et nettoyé.")

        # --- Feuille Origines ---
        print(f"Lecture du fichier origines : {fichier_origines_path}")
        origins_df_raw = pd.read_csv(fichier_origines_path, dtype=str)
        # CORRECTION CRITIQUE : Nettoyer la colonne 'id' AVANT de la définir comme index
        origins_df_raw['id'] = origins_df_raw['id'].str.strip()
        origins_df_raw['daily_loading_capacity_tons'] = clean_numeric_column(origins_df_raw['daily_loading_capacity_tons']).astype(float)
        origins_df_raw['initial_available_product_tons'] = clean_numeric_column(origins_df_raw['initial_available_product_tons']).astype(float)
        origins_df = origins_df_raw.set_index('id')
        print(f"  - Fichier '{fichier_origines_path}' ({len(origins_df)} lignes) lu, nettoyé et indexé sur 'id'.")
        
        # --- Feuille Destinations ---
        print(f"Lecture du fichier destinations : {fichier_destinations_path}")
        destinations_df_raw = pd.read_csv(fichier_destinations_path, dtype=str)
        # CORRECTION : Nettoyer la colonne 'id' par sécurité
        destinations_df_raw['id'] = destinations_df_raw['id'].str.strip()
        destinations_df_raw['daily_unloading_capacity_tons'] = clean_numeric_column(destinations_df_raw['daily_unloading_capacity_tons']).astype(float)
        destinations_df_raw['annual_demand_tons'] = clean_numeric_column(destinations_df_raw['annual_demand_tons']).astype(float)
        destinations_df = destinations_df_raw.set_index('id')
        print(f"  - Fichier '{fichier_destinations_path}' ({len(destinations_df)} lignes) lu, nettoyé et indexé sur 'id'.")
        
        print("Données CSV chargées et nettoyées avec succès.")
        return relations_df, origins_df, destinations_df
        
    except FileNotFoundError as fnf_error:
        print(f"ERREUR FATALE: Un fichier CSV d'entrée n'a pas été trouvé : {fnf_error}")
        print("Veuillez vous assurer que les fichiers CSV existent au bon emplacement et que les noms sont corrects.")
        raise
    except ValueError as ve: 
        print(f"ERREUR FATALE lors du chargement ou nettoyage des données CSV : {ve}")
        raise
    except Exception as e: 
        print(f"ERREUR FATALE inattendue lors du chargement ou nettoyage des données CSV: {e}")
        import traceback
        traceback.print_exc()
        raise

# --- 2. Initialiser les variables de suivi (Commun) ---
def initialize_tracking_variables(origins_df, destinations_df, num_initial_wagons=100):
    origins_df_sim = origins_df.copy()
    destinations_df_sim = destinations_df.copy()
    
    required_cols_orig = ['initial_available_product_tons', 'daily_loading_capacity_tons']
    for col in required_cols_orig:
        if col not in origins_df.columns:
            raise KeyError(f"La colonne interne requise '{col}' est manquante dans origins_df.")
            
    required_cols_dest = ['annual_demand_tons', 'daily_unloading_capacity_tons']
    for col in required_cols_dest:
        if col not in destinations_df.columns:
            raise KeyError(f"La colonne interne requise '{col}' est manquante dans destinations_df.")

    origins_df_sim['current_available_product_tons'] = origins_df_sim['initial_available_product_tons'].astype(float)
    destinations_df_sim['delivered_so_far_tons'] = 0.0
    destinations_df_sim['remaining_annual_demand_tons'] = destinations_df_sim['annual_demand_tons'].astype(float)
    destinations_df_sim['q_min_initial_target_tons'] = 0.20 * destinations_df_sim['annual_demand_tons']
    destinations_df_sim['q_min_initial_delivered_tons'] = 0.0
    tracking_vars = {
        'wagons_available': num_initial_wagons,
        'wagons_in_transit': [],
        'shipments_log': [],
        'daily_wagon_log': [] 
    }
    return origins_df_sim, destinations_df_sim, tracking_vars

# --- Fonction utilitaire pour gérer une expédition (Commun) ---
def process_shipment(day_t, origin_id, dest_id, distance_km, desired_qty,
                     origins_df, destinations_df, tracking_vars,
                     origin_daily_loading_cap_remaining, dest_daily_unloading_cap_remaining,
                     log_prefix=""):
    if desired_qty <= EPSILON: return 0.0, 0, origin_daily_loading_cap_remaining, dest_daily_unloading_cap_remaining
    if desired_qty < MIN_SHIPMENT_FOR_ONE_WAGON_TONS: return 0.0, 0, origin_daily_loading_cap_remaining, dest_daily_unloading_cap_remaining
    
    if origin_id not in origins_df.index:
        return 0.0, 0, origin_daily_loading_cap_remaining, dest_daily_unloading_cap_remaining
    if dest_id not in destinations_df.index:
        return 0.0, 0, origin_daily_loading_cap_remaining, dest_daily_unloading_cap_remaining

    qty_can_load = min(desired_qty, origin_daily_loading_cap_remaining, origins_df.loc[origin_id, 'current_available_product_tons'])
    qty_can_unload_and_demand = min(desired_qty, dest_daily_unloading_cap_remaining, destinations_df.loc[dest_id, 'remaining_annual_demand_tons'])
    potential_qty_to_ship = min(qty_can_load, qty_can_unload_and_demand)
    if potential_qty_to_ship < MIN_SHIPMENT_FOR_ONE_WAGON_TONS: return 0.0, 0, origin_daily_loading_cap_remaining, dest_daily_unloading_cap_remaining
    if potential_qty_to_ship <= EPSILON: return 0.0, 0, origin_daily_loading_cap_remaining, dest_daily_unloading_cap_remaining
    wagons_needed_ideal = math.ceil(potential_qty_to_ship / WAGON_CAPACITY_TONS)
    if tracking_vars['wagons_available'] == 0: return 0.0, 0, origin_daily_loading_cap_remaining, dest_daily_unloading_cap_remaining
    wagons_to_use = min(wagons_needed_ideal, tracking_vars['wagons_available'])
    actual_qty_to_ship = min(potential_qty_to_ship, wagons_to_use * WAGON_CAPACITY_TONS)
    if actual_qty_to_ship < MIN_SHIPMENT_FOR_ONE_WAGON_TONS and actual_qty_to_ship > EPSILON: return 0.0, 0, origin_daily_loading_cap_remaining, dest_daily_unloading_cap_remaining
    if actual_qty_to_ship <= EPSILON: return 0.0, 0, origin_daily_loading_cap_remaining, dest_daily_unloading_cap_remaining
    final_wagons_used = math.ceil(actual_qty_to_ship / WAGON_CAPACITY_TONS)
    if final_wagons_used > tracking_vars['wagons_available']: return 0.0, 0, origin_daily_loading_cap_remaining, dest_daily_unloading_cap_remaining
    
    origins_df.loc[origin_id, 'current_available_product_tons'] -= actual_qty_to_ship
    destinations_df.loc[dest_id, 'delivered_so_far_tons'] += actual_qty_to_ship
    destinations_df.loc[dest_id, 'remaining_annual_demand_tons'] -= actual_qty_to_ship
    origin_daily_loading_cap_remaining -= actual_qty_to_ship
    dest_daily_unloading_cap_remaining -= actual_qty_to_ship
    tracking_vars['wagons_available'] -= final_wagons_used
    aller_days = max(1, math.ceil(distance_km / KM_PER_DAY_FOR_WAGON_RETURN))
    day_of_return = day_t + (2 * aller_days); day_of_arrival_at_dest = day_t + aller_days
    tracking_vars['wagons_in_transit'].append({'return_day': day_of_return, 'num_wagons': final_wagons_used})
    tracking_vars['shipments_log'].append({
        'ship_day': day_t, 'arrival_day': day_of_arrival_at_dest, 'origin': origin_id, 'destination': dest_id,
        'quantity_tons': actual_qty_to_ship, 'wagons_used': final_wagons_used, 'type': log_prefix.strip() or "Standard"
    })
    return actual_qty_to_ship, final_wagons_used, origin_daily_loading_cap_remaining, dest_daily_unloading_cap_remaining

# --- Fonction pour obtenir l'itérateur de destinations (H1) ---
def get_destination_iterator_h1(destinations_df_to_sort, sort_config):
    if sort_config is None: return None
    sort_type = sort_config[0]
    if sort_type == 'custom_order':
        custom_order_list = sort_config[1]
        return [dest_id for dest_id in custom_order_list if dest_id in destinations_df_to_sort.index]
    elif sort_type in ['q_min_initial_target_tons', 'annual_demand_tons', 'remaining_annual_demand_tons', 'min_distance_km']:
        sort_column, ascending_order = sort_type, sort_config[1]
        if sort_column in destinations_df_to_sort.columns:
            return destinations_df_to_sort.sort_values(by=sort_column, ascending=ascending_order).index.tolist()
    return None

# --- Fonctions spécifiques à H1 ---
def attempt_initial_q_min_delivery_h1(relations_df, origins_df, destinations_df, tracking_vars,
                                   dest_sort_config=None, silent_mode=False):
    day_for_q_min_shipments = 1
    q_min_origin_caps = origins_df['daily_loading_capacity_tons'].copy()
    q_min_dest_caps = destinations_df['daily_unloading_capacity_tons'].copy()
    iterator = get_destination_iterator_h1(destinations_df, dest_sort_config)
    if iterator is None:
        if not silent_mode: print("INFO H1: QMIN Initial - Ordre non valide. Tri par défaut (q_min_target décroissant).")
        iterator = destinations_df.sort_values(by='q_min_initial_target_tons', ascending=False).index.tolist()
    for dest_id in iterator:
        if dest_id not in destinations_df.index: continue 
        needed = destinations_df.loc[dest_id, 'q_min_initial_target_tons'] - destinations_df.loc[dest_id, 'q_min_initial_delivered_tons']
        if needed <= EPSILON: continue
        possible_rels = relations_df[relations_df['destination'] == dest_id].copy().merge(
            origins_df[['current_available_product_tons']], left_on='origin', right_index=True
        ).sort_values(by='current_available_product_tons', ascending=False)
        for _, rel in possible_rels.iterrows():
            orig_id, dist_km = rel['origin'], rel['distance_km']
            if needed <= EPSILON: break
            if orig_id not in origins_df.index: continue 
            if q_min_origin_caps.get(orig_id,0) <= EPSILON or q_min_dest_caps.get(dest_id,0) <= EPSILON or \
               origins_df.loc[orig_id, 'current_available_product_tons'] <= EPSILON: continue
            shipped, wagons_used, new_orig_cap, new_dest_cap = process_shipment(
                day_for_q_min_shipments, orig_id, dest_id, dist_km, needed, origins_df, destinations_df, tracking_vars,
                q_min_origin_caps[orig_id], q_min_dest_caps[dest_id], "[QMIN_INIT_J1_H1]"
            )
            if shipped > EPSILON:
                q_min_origin_caps[orig_id], q_min_dest_caps[dest_id] = new_orig_cap, new_dest_cap
                destinations_df.loc[dest_id, 'q_min_initial_delivered_tons'] += shipped; needed -= shipped
    return origins_df, destinations_df, tracking_vars, q_min_origin_caps, q_min_dest_caps

def filter_profitable_relations_h1(relations_df):
    return relations_df[relations_df['profitability'] == 1].copy()

def run_simulation_h1(relations_input_df, origins_input_df, destinations_input_df,
                      qmin_common_config=None, phase2_config=None,
                      num_initial_wagons_param=500, silent_mode=False):
    relations_df = relations_input_df.copy()
    origins_df, destinations_df, tracking_vars_sim = initialize_tracking_variables(
        origins_input_df.copy(), destinations_input_df.copy(), num_initial_wagons_param
    )
    origins_df, destinations_df, tracking_vars_sim, rem_load_d1, rem_unload_d1 = \
        attempt_initial_q_min_delivery_h1(relations_df, origins_df, destinations_df, tracking_vars_sim,
                                          qmin_common_config, silent_mode)
    profitable_relations_df = filter_profitable_relations_h1(relations_df)
    all_total_dem_met = False; last_day_of_shipment = 0; day_t = 0
    for day_t_loop in range(1, MAX_SIMULATION_DAYS + 1):
        day_t = day_t_loop
        
        wagons_shipped_this_day = 0
        returned_wagons = 0; active_transit = []
        for ti in tracking_vars_sim['wagons_in_transit']:
            if ti['return_day'] == day_t: returned_wagons += ti['num_wagons']
            elif ti['return_day'] > day_t: active_transit.append(ti)
        
        wagons_available_at_start = tracking_vars_sim['wagons_available'] + returned_wagons
        tracking_vars_sim['wagons_available'] = wagons_available_at_start
        tracking_vars_sim['wagons_in_transit'] = active_transit
        
        curr_orig_load = rem_load_d1.copy() if day_t == 1 else origins_df['daily_loading_capacity_tons'].copy()
        curr_dest_unload = rem_unload_d1.copy() if day_t == 1 else destinations_df['daily_unloading_capacity_tons'].copy()
        shipments_today = False
        
        qmin_daily_iter = get_destination_iterator_h1(destinations_df, qmin_common_config)
        if qmin_daily_iter is None: 
            if not silent_mode: print("INFO H1: QMIN Daily - Ordre non valide. Tri par défaut.")
            qmin_daily_iter = destinations_df.sort_values(by='q_min_initial_target_tons', ascending=False).index.tolist()
        for dest_id in qmin_daily_iter:
            if dest_id not in destinations_df.index: continue
            needed = destinations_df.loc[dest_id, 'q_min_initial_target_tons'] - destinations_df.loc[dest_id, 'q_min_initial_delivered_tons']
            if needed <= EPSILON: continue
            rels_for_qmin = relations_df[relations_df['destination'] == dest_id].copy().merge(
                origins_df[['current_available_product_tons']], left_on='origin', right_index=True
            ).sort_values(by='current_available_product_tons', ascending=False)
            for _, rel in rels_for_qmin.iterrows():
                orig_id, dist_km = rel['origin'], rel['distance_km']
                if needed <= EPSILON: break
                if orig_id not in origins_df.index: continue
                if curr_orig_load.get(orig_id,0) <= EPSILON or curr_dest_unload.get(dest_id,0) <= EPSILON or \
                   origins_df.loc[orig_id, 'current_available_product_tons'] <= EPSILON: continue
                shipped, wagons_used, n_orig_cap, n_dest_cap = process_shipment(
                    day_t, orig_id, dest_id, dist_km, needed, origins_df, destinations_df, tracking_vars_sim,
                    curr_orig_load[orig_id], curr_dest_unload[dest_id], "[QMIN_DAILY_H1]"
                )
                if shipped > EPSILON:
                    wagons_shipped_this_day += wagons_used
                    curr_orig_load[orig_id], curr_dest_unload[dest_id] = n_orig_cap, n_dest_cap
                    destinations_df.loc[dest_id, 'q_min_initial_delivered_tons'] += shipped
                    needed -= shipped; shipments_today = True; last_day_of_shipment = day_t
        
        sorted_origins = origins_df.sort_values(by='current_available_product_tons', ascending=False).index
        for orig_id in sorted_origins:
            if orig_id not in origins_df.index: continue
            if origins_df.loc[orig_id, 'current_available_product_tons'] <= EPSILON or curr_orig_load.get(orig_id,0) <= EPSILON: continue
            rels_from_orig = profitable_relations_df[profitable_relations_df['origin'] == orig_id].copy()
            if rels_from_orig.empty: continue
            dest_ids_for_orig = rels_from_orig['destination'].unique()
            valid_dest_ids_for_orig = [d_id for d_id in dest_ids_for_orig if d_id in destinations_df.index]
            if not valid_dest_ids_for_orig: continue
            temp_dest_df = destinations_df.loc[valid_dest_ids_for_orig].copy()
            phase2_iter = get_destination_iterator_h1(temp_dest_df, phase2_config)
            relation_iterator_data = []
            if phase2_iter is None: 
                if not silent_mode: print(f"INFO H1: Phase 2 (Origine {orig_id}) - Ordre non valide. Tri par défaut (demande restante).")
                relation_iterator_data = rels_from_orig[rels_from_orig['destination'].isin(valid_dest_ids_for_orig)].merge(
                    destinations_df[['remaining_annual_demand_tons']], left_on='destination', right_index=True
                ).sort_values(by='remaining_annual_demand_tons', ascending=False).iterrows()
            else:
                ordered_rels = []
                for dest_id_ord in phase2_iter:
                    matching = rels_from_orig[rels_from_orig['destination'] == dest_id_ord]
                    for _, r_row in matching.iterrows(): ordered_rels.append(r_row)
                relation_iterator_data = [(idx, series) for idx, series in enumerate(ordered_rels)]
            for _, rel_data in relation_iterator_data:
                dest_id, dist_km = rel_data['destination'], rel_data['distance_km']
                if dest_id not in destinations_df.index: continue 
                if destinations_df.loc[dest_id, 'q_min_initial_delivered_tons'] < (destinations_df.loc[dest_id, 'q_min_initial_target_tons'] - EPSILON): continue
                if curr_orig_load.get(orig_id,0) <= EPSILON or (tracking_vars_sim['wagons_available'] == 0 and dist_km > 0): break
                if destinations_df.loc[dest_id, 'remaining_annual_demand_tons'] <= EPSILON or curr_dest_unload.get(dest_id,0) <= EPSILON: continue
                desired_qty = destinations_df.loc[dest_id, 'remaining_annual_demand_tons']
                if desired_qty <= EPSILON: continue
                shipped, wagons_used, n_orig_cap, n_dest_cap = process_shipment(
                    day_t, orig_id, dest_id, dist_km, desired_qty, origins_df, destinations_df, tracking_vars_sim,
                    curr_orig_load[orig_id], curr_dest_unload[dest_id], "[SIM_PROFIT_H1]"
                )
                if shipped > EPSILON:
                    wagons_shipped_this_day += wagons_used
                    curr_orig_load[orig_id], curr_dest_unload[dest_id] = n_orig_cap, n_dest_cap
                    shipments_today = True; last_day_of_shipment = day_t
        
        tracking_vars_sim['daily_wagon_log'].append({
            'day': day_t,
            'available_start': wagons_available_at_start,
            'returned': returned_wagons,
            'sent': wagons_shipped_this_day,
            'available_end': tracking_vars_sim['wagons_available'],
            'in_transit_end': sum(w['num_wagons'] for w in tracking_vars_sim['wagons_in_transit'])
        })
        
        all_total_dem_met = (destinations_df['remaining_annual_demand_tons'] <= EPSILON).all()
        if all_total_dem_met:
            if not silent_mode: print(f"\n--- Simulation H1 terminée au jour {day_t}: Toutes les demandes sont satisfaites. ---")
            break
        if not shipments_today:
            no_prod = (origins_df['current_available_product_tons'] <= EPSILON).all()
            no_wagons_ever_returning = (tracking_vars_sim['wagons_available'] == 0 and not tracking_vars_sim['wagons_in_transit'])
            if no_prod and no_wagons_ever_returning:
                if not silent_mode: print(f"\n--- FIN H1 Jour {day_t}: Plus de produit ET plus de wagons (et aucun en retour). ---")
                break
            elif no_prod:
                q_min_still_needed = (destinations_df['q_min_initial_delivered_tons'] < (destinations_df['q_min_initial_target_tons'] - EPSILON)).any()
                demand_still_exists = (destinations_df['remaining_annual_demand_tons'] > EPSILON).any()
                if not (q_min_still_needed or demand_still_exists):
                    if not silent_mode: print(f"\n--- FIN H1 Jour {day_t}: Plus de produit et toutes demandes satisfaites. ---")
                    break
                elif no_wagons_ever_returning:
                    if not silent_mode: print(f"\n--- FIN H1 Jour {day_t}: Plus de produit ET plus de wagons (et aucun en retour), mais avec demandes restantes. ---")
                    break
            elif no_wagons_ever_returning:
                if not silent_mode: print(f"\n--- FIN H1 Jour {day_t}: Plus de wagons (et aucun en retour), mais avec produit et demandes restantes. ---")
                break
    if day_t >= MAX_SIMULATION_DAYS and not all_total_dem_met:
        if not silent_mode: print(f"\n--- FIN H1: Limite de {MAX_SIMULATION_DAYS} jours atteinte. Demandes non toutes satisfaites. ---")
    shipments_summary_df = pd.DataFrame(tracking_vars_sim['shipments_log'])
    profit_metric = 0.0
    if not shipments_summary_df.empty:
        temp_df = shipments_summary_df.copy()
        temp_df = temp_df.merge(relations_input_df[['origin', 'destination', 'distance_km']],
                                on=['origin', 'destination'], how='left')
        temp_df.fillna({'distance_km': 0}, inplace=True)
        profit_metric = (temp_df['quantity_tons'] * temp_df['distance_km']).sum()
    return {
        "profit": profit_metric, "shipments_df": shipments_summary_df, "final_origins_df": origins_df,
        "final_destinations_df": destinations_df, "final_tracking_vars": tracking_vars_sim,
        "all_demand_met": all_total_dem_met, "days_taken_simulation_loop": day_t
    }

# --- Fonctions spécifiques à H2 ---
def run_simulation_h2(relations_input_df, origins_input_df, destinations_input_df,
                      qmin_user_priority_order=None,
                      standard_shipment_dest_priority_order=None,
                      num_initial_wagons_param=50, silent_mode=False):
    relations_df = relations_input_df.copy()
    origins_df, destinations_df, tracking_vars_sim = initialize_tracking_variables(
        origins_input_df.copy(), destinations_input_df.copy(), num_initial_wagons_param
    )
    qmin_config_for_attempt = ('custom_order', qmin_user_priority_order) if qmin_user_priority_order else None
    origins_df, destinations_df, tracking_vars_sim, rem_load_d1, rem_unload_d1 = \
        attempt_initial_q_min_delivery_h1(relations_df, origins_df, destinations_df, tracking_vars_sim,
                                          qmin_config_for_attempt, silent_mode) 
    profitable_relations_df = filter_profitable_relations_h1(relations_df)
    all_total_dem_met = False; last_day_of_shipment = 0; day_t = 0
    for day_t_loop in range(1, MAX_SIMULATION_DAYS + 1):
        day_t = day_t_loop
        
        wagons_shipped_this_day = 0
        returned_wagons = 0; active_transit = []
        for ti in tracking_vars_sim['wagons_in_transit']:
            if ti['return_day'] == day_t: returned_wagons += ti['num_wagons']
            elif ti['return_day'] > day_t: active_transit.append(ti)
            
        wagons_available_at_start = tracking_vars_sim['wagons_available'] + returned_wagons
        tracking_vars_sim['wagons_available'] = wagons_available_at_start
        tracking_vars_sim['wagons_in_transit'] = active_transit

        curr_orig_load = rem_load_d1.copy() if day_t == 1 else origins_df['daily_loading_capacity_tons'].copy()
        curr_dest_unload = rem_unload_d1.copy() if day_t == 1 else destinations_df['daily_unloading_capacity_tons'].copy()
        shipments_today = False
        
        qmin_daily_iter_h2 = None
        if qmin_user_priority_order:
            qmin_daily_iter_h2 = [dest_id for dest_id in qmin_user_priority_order if dest_id in destinations_df.index]
        if qmin_daily_iter_h2 is None or not qmin_daily_iter_h2:
            if not silent_mode: print("INFO H2: QMIN Daily - Ordre non valide/fourni. Tri par défaut.")
            qmin_daily_iter_h2 = destinations_df.sort_values(by='q_min_initial_target_tons', ascending=False).index.tolist()
        for dest_id in qmin_daily_iter_h2:
            if dest_id not in destinations_df.index: continue
            needed = destinations_df.loc[dest_id, 'q_min_initial_target_tons'] - destinations_df.loc[dest_id, 'q_min_initial_delivered_tons']
            if needed <= EPSILON: continue
            rels_for_qmin = relations_df[relations_df['destination'] == dest_id].copy().merge(
                origins_df[['current_available_product_tons']], left_on='origin', right_index=True
            ).sort_values(by='current_available_product_tons', ascending=False)
            for _, rel in rels_for_qmin.iterrows():
                orig_id, dist_km = rel['origin'], rel['distance_km']
                if needed <= EPSILON: break
                if orig_id not in origins_df.index: continue
                if curr_orig_load.get(orig_id,0) <= EPSILON or curr_dest_unload.get(dest_id,0) <= EPSILON or \
                   origins_df.loc[orig_id, 'current_available_product_tons'] <= EPSILON: continue
                shipped, wagons_used, n_orig_cap, n_dest_cap = process_shipment(
                    day_t, orig_id, dest_id, dist_km, needed, origins_df, destinations_df, tracking_vars_sim,
                    curr_orig_load[orig_id], curr_dest_unload[dest_id], "[QMIN_DAILY_H2]"
                )
                if shipped > EPSILON:
                    wagons_shipped_this_day += wagons_used
                    curr_orig_load[orig_id], curr_dest_unload[dest_id] = n_orig_cap, n_dest_cap
                    destinations_df.loc[dest_id, 'q_min_initial_delivered_tons'] += shipped
                    needed -= shipped; shipments_today = True; last_day_of_shipment = day_t
        
        phase2_dest_iter_h2 = None
        if standard_shipment_dest_priority_order:
            phase2_dest_iter_h2 = [dest_id for dest_id in standard_shipment_dest_priority_order if dest_id in destinations_df.index and destinations_df.loc[dest_id, 'remaining_annual_demand_tons'] > EPSILON]
        if phase2_dest_iter_h2 is None or not phase2_dest_iter_h2:
            if not silent_mode: print("INFO H2: Phase 2 - Ordre non valide/fourni. Tri par défaut.")
            phase2_dest_iter_h2 = destinations_df[destinations_df['remaining_annual_demand_tons'] > EPSILON]\
                                   .sort_values(by='remaining_annual_demand_tons', ascending=False).index
        for dest_id in phase2_dest_iter_h2:
            if dest_id not in destinations_df.index: continue 
            if destinations_df.loc[dest_id, 'q_min_initial_delivered_tons'] < (destinations_df.loc[dest_id, 'q_min_initial_target_tons'] - EPSILON): continue
            if curr_dest_unload.get(dest_id, 0) <= EPSILON or destinations_df.loc[dest_id, 'remaining_annual_demand_tons'] <= EPSILON: continue
            best_origin_for_dest = None; best_origin_dist_km = 0; max_rentabilite_metric = -1.0
            candidate_relations = profitable_relations_df[profitable_relations_df['destination'] == dest_id]
            for _, rel in candidate_relations.iterrows():
                orig_id, dist_km = rel['origin'], rel['distance_km']
                if orig_id not in origins_df.index: continue
                if origins_df.loc[orig_id, 'current_available_product_tons'] <= EPSILON or curr_orig_load.get(orig_id, 0) <= EPSILON: continue
                if tracking_vars_sim['wagons_available'] == 0 and dist_km > 0: continue
                potential_qty = min(origins_df.loc[orig_id, 'current_available_product_tons'], curr_orig_load.get(orig_id, 0),
                                    curr_dest_unload.get(dest_id, 0), destinations_df.loc[dest_id, 'remaining_annual_demand_tons'])
                if potential_qty < MIN_SHIPMENT_FOR_ONE_WAGON_TONS: continue
                current_rentabilite_metric = potential_qty * dist_km 
                if current_rentabilite_metric > max_rentabilite_metric:
                    max_rentabilite_metric = current_rentabilite_metric
                    best_origin_for_dest = orig_id; best_origin_dist_km = dist_km
            if best_origin_for_dest is not None and max_rentabilite_metric >= 0 :
                desired_std_qty = destinations_df.loc[dest_id, 'remaining_annual_demand_tons']
                shipped_qty, wagons_used, n_orig_cap, n_dest_cap = process_shipment(
                    day_t, best_origin_for_dest, dest_id, best_origin_dist_km, desired_std_qty,
                    origins_df, destinations_df, tracking_vars_sim,
                    curr_orig_load[best_origin_for_dest], curr_dest_unload[dest_id], log_prefix="[SIM_PROFIT_H2]"
                )
                if shipped_qty > EPSILON:
                    wagons_shipped_this_day += wagons_used
                    curr_orig_load[best_origin_for_dest] = n_orig_cap; curr_dest_unload[dest_id] = n_dest_cap
                    shipments_today = True

        tracking_vars_sim['daily_wagon_log'].append({
            'day': day_t,
            'available_start': wagons_available_at_start,
            'returned': returned_wagons,
            'sent': wagons_shipped_this_day,
            'available_end': tracking_vars_sim['wagons_available'],
            'in_transit_end': sum(w['num_wagons'] for w in tracking_vars_sim['wagons_in_transit'])
        })
        
        all_total_dem_met = (destinations_df['remaining_annual_demand_tons'] <= EPSILON).all()
        if all_total_dem_met:
            if not silent_mode: print(f"\n--- Simulation H2 terminée au jour {day_t}: Toutes les demandes sont satisfaites. ---")
            break
        if not shipments_today: 
            no_prod = (origins_df['current_available_product_tons'] <= EPSILON).all()
            no_wagons_ever_returning = (tracking_vars_sim['wagons_available'] == 0 and not tracking_vars_sim['wagons_in_transit'])
            if no_prod and no_wagons_ever_returning:
                if not silent_mode: print(f"\n--- FIN H2 Jour {day_t}: Plus de produit ET plus de wagons (et aucun en retour). ---")
                break
            elif no_prod:
                q_min_still_needed = (destinations_df['q_min_initial_delivered_tons'] < (destinations_df['q_min_initial_target_tons'] - EPSILON)).any()
                demand_still_exists = (destinations_df['remaining_annual_demand_tons'] > EPSILON).any()
                if not (q_min_still_needed or demand_still_exists):
                    if not silent_mode: print(f"\n--- FIN H2 Jour {day_t}: Plus de produit et toutes demandes satisfaites. ---")
                    break
                elif no_wagons_ever_returning:
                    if not silent_mode: print(f"\n--- FIN H2 Jour {day_t}: Plus de produit ET plus de wagons (et aucun en retour), mais avec demandes restantes. ---")
                    break
            elif no_wagons_ever_returning:
                if not silent_mode: print(f"\n--- FIN H2 Jour {day_t}: Plus de wagons (et aucun en retour), mais avec produit et demandes restantes. ---")
                break 
    if day_t >= MAX_SIMULATION_DAYS and not all_total_dem_met:
        if not silent_mode: print(f"\n--- FIN H2: Limite de {MAX_SIMULATION_DAYS} jours atteinte. Demandes non toutes satisfaites. ---")
    shipments_summary_df = pd.DataFrame(tracking_vars_sim['shipments_log'])
    profit_metric = 0.0
    if not shipments_summary_df.empty:
        temp_df = shipments_summary_df.copy()
        temp_df = temp_df.merge(relations_input_df[['origin', 'destination', 'distance_km']],
                                on=['origin', 'destination'], how='left')
        temp_df.fillna({'distance_km': 0}, inplace=True)
        profit_metric = (temp_df['quantity_tons'] * temp_df['distance_km']).sum()
    return {
        "profit": profit_metric, "shipments_df": shipments_summary_df, "final_origins_df": origins_df,
        "final_destinations_df": destinations_df, "final_tracking_vars": tracking_vars_sim,
        "all_demand_met": all_total_dem_met, "days_taken_simulation_loop": day_t
    }

# --- Fonctions pour la méthode de montée (communes en logique) ---
def generate_custom_order_neighbors(current_custom_order_list):
    neighbors = []; n = len(current_custom_order_list)
    if n >= 2:
        for i in range(n):
            for j in range(i + 1, n):
                neighbor_order = current_custom_order_list[:]; neighbor_order[i], neighbor_order[j] = neighbor_order[j], neighbor_order[i]
                neighbors.append(neighbor_order)
    return neighbors

# --- Hill Climbing pour H1 ---
def hill_climbing_maximizer_h1(rels_df_hc, orig_df_hc, dest_df_hc, 
                               initial_qmin_config_tuple, initial_phase2_config_tuple, 
                               num_initial_wagons, max_iterations=10):
    current_best_qmin_cfg = initial_qmin_config_tuple
    current_best_phase2_cfg = initial_phase2_config_tuple
    eval_result = run_simulation_h1(rels_df_hc, orig_df_hc, dest_df_hc,
                                    current_best_qmin_cfg, current_best_phase2_cfg, num_initial_wagons, True)
    current_best_profit_overall = eval_result['profit']
    print(f"\nProfit initial pour l'optimisation (H1): {current_best_profit_overall:.2f}")
    print(f"  Config QMIN (H1): {current_best_qmin_cfg}")
    print(f"  Config Phase 2 (H1): {current_best_phase2_cfg}")
    for iteration in range(max_iterations):
        print(f"\n--- Itération de Montée H1 {iteration + 1}/{max_iterations} (Meilleur Profit Actuel: {current_best_profit_overall:.2f}) ---")
        made_improvement = False
        if current_best_qmin_cfg and current_best_qmin_cfg[0] == 'custom_order' and len(current_best_qmin_cfg[1]) >= 2:
            for neighbor_qmin_list in generate_custom_order_neighbors(current_best_qmin_cfg[1]):
                neighbor_qmin_cfg = ('custom_order', neighbor_qmin_list)
                print(f"    H1 Test QMIN: {neighbor_qmin_list}")
                eval_n = run_simulation_h1(rels_df_hc, orig_df_hc, dest_df_hc,
                                           neighbor_qmin_cfg, current_best_phase2_cfg, num_initial_wagons, True)
                print(f"      Profit obtenu: {eval_n['profit']:.2f}")
                if eval_n['profit'] > current_best_profit_overall:
                    print(f"       >>> H1 Amélioration via QMIN: {eval_n['profit']:.2f}")
                    current_best_profit_overall = eval_n['profit']; current_best_qmin_cfg = neighbor_qmin_cfg
                    made_improvement = True
                    print(f"        Nouvelle Config QMIN (H1): {current_best_qmin_cfg}")
        if current_best_phase2_cfg and current_best_phase2_cfg[0] == 'custom_order' and len(current_best_phase2_cfg[1]) >= 2:
            for neighbor_ph2_list in generate_custom_order_neighbors(current_best_phase2_cfg[1]):
                neighbor_ph2_cfg = ('custom_order', neighbor_ph2_list)
                print(f"    H1 Test Phase2: {neighbor_ph2_list}")
                eval_n = run_simulation_h1(rels_df_hc, orig_df_hc, dest_df_hc,
                                           current_best_qmin_cfg, neighbor_ph2_cfg, num_initial_wagons, True)
                print(f"      Profit obtenu: {eval_n['profit']:.2f}")
                if eval_n['profit'] > current_best_profit_overall:
                    print(f"       >>> H1 Amélioration via Phase2: {eval_n['profit']:.2f}")
                    current_best_profit_overall = eval_n['profit']; current_best_phase2_cfg = neighbor_ph2_cfg
                    made_improvement = True
                    print(f"        Nouvelle Config Phase 2 (H1): {current_best_phase2_cfg}")
        if not made_improvement: print("Aucune amélioration H1 dans cette itération."); break
    print("\n--- Fin de l'Optimisation H1 ---")
    print(f"Meilleur profit H1: {current_best_profit_overall:.2f}")
    print(f"  Meilleure Config QMIN (H1): {current_best_qmin_cfg}")
    print(f"  Meilleure Config Phase 2 (H1): {current_best_phase2_cfg}")
    return (current_best_qmin_cfg, current_best_qmin_cfg, current_best_phase2_cfg)

# --- Hill Climbing pour H2 ---
def hill_climbing_maximizer_h2(rels_df_hc, orig_df_hc, dest_df_hc,
                               initial_qmin_order_list, initial_phase2_order_list, 
                               num_initial_wagons, max_iterations=10):
    current_best_qmin_order = initial_qmin_order_list
    current_best_phase2_order = initial_phase2_order_list
    eval_result = run_simulation_h2(rels_df_hc, orig_df_hc, dest_df_hc,
                                    current_best_qmin_order,current_best_phase2_order,num_initial_wagons, True)
    current_best_profit_overall = eval_result['profit']
    print(f"\nProfit initial pour l'optimisation (H2): {current_best_profit_overall:.2f}")
    print(f"  Ordre QMIN (H2): {current_best_qmin_order}")
    print(f"  Ordre Phase 2 (H2): {current_best_phase2_order}")
    for iteration in range(max_iterations):
        print(f"\n--- Itération de Montée H2 {iteration + 1}/{max_iterations} (Meilleur Profit Actuel: {current_best_profit_overall:.2f}) ---")
        made_improvement = False
        if current_best_qmin_order and len(current_best_qmin_order) >= 2:
            for neighbor_qmin_list in generate_custom_order_neighbors(current_best_qmin_order):
                print(f"    H2 Test QMIN: {neighbor_qmin_list}")
                eval_n = run_simulation_h2(rels_df_hc, orig_df_hc, dest_df_hc,
                                           neighbor_qmin_list, current_best_phase2_order, num_initial_wagons, True)
                print(f"      Profit obtenu: {eval_n['profit']:.2f}")
                if eval_n['profit'] > current_best_profit_overall:
                    print(f"       >>> H2 Amélioration via QMIN: {eval_n['profit']:.2f}")
                    current_best_profit_overall = eval_n['profit']; current_best_qmin_order = neighbor_qmin_list
                    made_improvement = True
                    print(f"        Nouvel Ordre QMIN (H2): {current_best_qmin_order}")
        if current_best_phase2_order and len(current_best_phase2_order) >= 2:
            for neighbor_ph2_list in generate_custom_order_neighbors(current_best_phase2_order):
                print(f"    H2 Test Phase2: {neighbor_ph2_list}")
                eval_n = run_simulation_h2(rels_df_hc, orig_df_hc, dest_df_hc,
                                           current_best_qmin_order, neighbor_ph2_list, num_initial_wagons, True)
                print(f"      Profit obtenu: {eval_n['profit']:.2f}")
                if eval_n['profit'] > current_best_profit_overall:
                    print(f"       >>> H2 Amélioration via Phase2: {eval_n['profit']:.2f}")
                    current_best_profit_overall = eval_n['profit']; current_best_phase2_order = neighbor_ph2_list
                    made_improvement = True
                    print(f"        Nouvel Ordre Phase2 (H2): {current_best_phase2_order}")
        if not made_improvement: print("Aucune amélioration H2 dans cette itération."); break
    print("\n--- Fin de l'Optimisation H2 ---")
    print(f"Meilleur profit H2: {current_best_profit_overall:.2f}")
    print(f"  Meilleur Ordre QMIN (H2): {current_best_qmin_order}")
    print(f"  Meilleur Ordre Phase 2 (H2): {current_best_phase2_order}")
    return (current_best_qmin_order, current_best_phase2_order)

# --- Affichage des Résultats (Commun) ---
def display_results_common(sim_res, rel_glob, dest_glob, orig_glob, heuristique_name=""):
    if not sim_res:
        print(f"\n\n--- Aucun résultat à afficher pour la Simulation ({heuristique_name}) ---")
        return

    profit = sim_res.get('profit', 0.0)
    days_loop = sim_res.get('days_taken_simulation_loop', 'N/A')
    all_met = sim_res.get('all_demand_met', False)

    print(f"\n\n--- Résultats de la Simulation ({heuristique_name}) ---")
    print(f"Indicateur de PROFIT total global (Tonnes * km) : {profit:.2f}")
    print(f"Toutes les demandes satisfaites : {'Oui' if all_met else 'Non'}")
    if all_met: print(f"Simulation terminée en {days_loop} jours (demande satisfaite).")
    else: print(f"Simulation arrêtée au jour {days_loop} (limite {MAX_SIMULATION_DAYS} jours ou blocage).")
    
    final_tracking_vars = sim_res.get('final_tracking_vars')
    shipments_df = sim_res.get('shipments_df')
    if shipments_df is not None and not shipments_df.empty:
        qmin_prefixes = ['[QMIN_INIT_J1_H1]', '[QMIN_DAILY_H1]', '[QMIN_INIT_J1_H2]', '[QMIN_DAILY_H2]', '[QMIN_INIT_J1]', '[QMIN_DAILY]']
        qmin_shipments_df = shipments_df[shipments_df['type'].isin(qmin_prefixes)].copy()
        if not qmin_shipments_df.empty:
            qmin_daily_total_to_yj = qmin_shipments_df.groupby(['ship_day', 'destination'])['quantity_tons'].sum().rename('Q_Qmin_Yj_Jr')
            qmin_daily_total_from_xi = qmin_shipments_df.groupby(['ship_day', 'origin'])['quantity_tons'].sum().rename('Q_Qmin_Xi_Jr')
            qmin_shipments_df = qmin_shipments_df.merge(dest_glob[['annual_demand_tons']], left_on='destination', right_index=True, how='left').rename(columns={'annual_demand_tons': 'Dem_Tot_Yj'})
            qmin_shipments_df = qmin_shipments_df.merge(rel_glob[['origin', 'destination', 'profitability']], on=['origin', 'destination'], how='left').rename(columns={'profitability': 'Rentab_Relation_Utilisee'})
            qmin_shipments_df['Rentab_Relation_Utilisee'] = qmin_shipments_df['Rentab_Relation_Utilisee'].map({1: 'Oui', 0: 'Non', True: 'Oui', False: 'Non'})
            qmin_shipments_df = qmin_shipments_df.merge(qmin_daily_total_to_yj, on=['ship_day', 'destination'], how='left').fillna({'Q_Qmin_Yj_Jr':0})
            qmin_shipments_df = qmin_shipments_df.merge(qmin_daily_total_from_xi, on=['ship_day', 'origin'], how='left').fillna({'Q_Qmin_Xi_Jr':0})
            print("\n--- Matrice des Expéditions QMIN (Vue Origine) ---")
            matrice1_qmin = qmin_shipments_df[['origin', 'ship_day', 'destination', 'quantity_tons','Dem_Tot_Yj', 'Rentab_Relation_Utilisee', 'Q_Qmin_Yj_Jr', 'type']].copy()
            matrice1_qmin.rename(columns={'origin': 'Orig', 'ship_day': 'Jr_Exp','destination': 'Dest', 'quantity_tons': 'Q_Exp_QMIN_Xi_Dest'}, inplace=True)
            print(matrice1_qmin.sort_values(by=['Jr_Exp', 'Orig', 'Dest']))
            print("\n--- Matrice des Expéditions QMIN (Vue Destination) ---")
            matrice2_qmin = qmin_shipments_df[['destination', 'ship_day', 'origin', 'quantity_tons','Dem_Tot_Yj', 'Rentab_Relation_Utilisee', 'Q_Qmin_Xi_Jr', 'type']].copy()
            matrice2_qmin.rename(columns={'destination': 'Dest', 'ship_day': 'Jr_Exp','origin': 'Orig', 'quantity_tons': 'Q_Exp_QMIN_Dest_Orig'}, inplace=True)
            print(matrice2_qmin.sort_values(by=['Jr_Exp', 'Dest', 'Orig']))
        else: print("Aucune expédition de type QMIN n'a été effectuée.")
        print("\n--- Toutes les Expéditions (Détail) ---")
        print(shipments_df.sort_values(by=['ship_day', 'origin', 'destination']))
    else: print("Aucune expédition à afficher en détail.")
    
    final_destinations_df_res = sim_res.get('final_destinations_df')
    if final_destinations_df_res is not None:
        print("\n--- Récapitulatif Final par Destination (Yj) ---")
        recap_dest_df = final_destinations_df_res.copy()
        recap_dest_df.index.name = 'Dest_Yj' 
        recap_dest_df = recap_dest_df.rename(columns={'q_min_initial_target_tons': 'Qmin_Cible_Yj', 'q_min_initial_delivered_tons': 'Qmin_Livre_Yj', 'delivered_so_far_tons': 'Total_Livre_Yj', 'remaining_annual_demand_tons': 'Dem_Rest_Yj'})
        if dest_glob is not None and 'annual_demand_tons' in dest_glob.columns:
            recap_dest_df = recap_dest_df.merge(dest_glob[['annual_demand_tons']].rename(columns={'annual_demand_tons':'Dem_Ann_Yj'}), left_index=True, right_index=True, how='left')
        else:
            recap_dest_df['Dem_Ann_Yj'] = 'N/A'
        cols_to_print_dest = [col for col in ['Dem_Ann_Yj', 'Qmin_Cible_Yj', 'Qmin_Livre_Yj', 'Total_Livre_Yj', 'Dem_Rest_Yj'] if col in recap_dest_df.columns]
        if cols_to_print_dest: print(recap_dest_df[cols_to_print_dest].round(2))
        else: print("Colonnes de récapitulatif de destination non trouvées.")

    final_origins_df_res = sim_res.get('final_origins_df')
    if final_origins_df_res is not None:
        print("\n--- Récapitulatif Final par Origine (Xi) ---")
        recap_orig_df = final_origins_df_res.copy()
        recap_orig_df.index.name = 'Orig_Xi' 
        if shipments_df is not None and not shipments_df.empty:
            total_expedie_par_xi = shipments_df.groupby('origin')['quantity_tons'].sum().rename('Total_Exp_Xi')
            recap_orig_df = recap_orig_df.merge(total_expedie_par_xi, left_index=True, right_index=True, how='left').fillna({'Total_Exp_Xi':0.0})
        else: recap_orig_df['Total_Exp_Xi'] = 0.0
        recap_orig_df = recap_orig_df.rename(columns={'current_available_product_tons': 'Stock_Fin_Xi'})
        if orig_glob is not None and 'initial_available_product_tons' in orig_glob.columns:
            recap_orig_df = recap_orig_df.merge(orig_glob[['initial_available_product_tons']].rename(columns={'initial_available_product_tons':'Stock_Initial_Global_Xi'}), left_index=True, right_index=True, how='left')
        else:
            recap_orig_df['Stock_Initial_Global_Xi'] = 'N/A'
        cols_to_print_orig = [col for col in ['Stock_Initial_Global_Xi', 'Total_Exp_Xi', 'Stock_Fin_Xi'] if col in recap_orig_df.columns]
        if cols_to_print_orig: print(recap_orig_df[cols_to_print_orig].round(2))
        else: print("Colonnes de récapitulatif d'origine non trouvées.")
    
    if final_tracking_vars:
        daily_wagon_log_df = pd.DataFrame(final_tracking_vars.get('daily_wagon_log', []))
        if not daily_wagon_log_df.empty:
            print("\n--- Suivi Quotidien des Wagons ---")
            print(daily_wagon_log_df.set_index('day'))
        
        print(f"\n--- Informations Finales sur les Wagons ---")
        print(f"Wagons restants disponibles à la fin: {final_tracking_vars['wagons_available']}")
        print(f"Wagons encore en transit à la fin: {sum(w['num_wagons'] for w in final_tracking_vars['wagons_in_transit'])}")

# --- Fonctions de saisie utilisateur ---
def get_user_custom_order_input(purpose_description, available_dest_ids):
    final_custom_list = None
    if not available_dest_ids:
        print(f"  AVERTISSEMENT: Aucune destination disponible pour '{purpose_description}'.")
        return [] 
    while final_custom_list is None:
        custom_str = input(f"  Entrez l'ordre des {len(available_dest_ids)} destinations pour '{purpose_description}' (séparées par virgules, ex: y1,y3,y2): ")
        custom_list_input = [d.strip() for d in custom_str.split(',') if d.strip()]
        is_valid_custom = True; seen_in_custom = set(); temp_list = []
        if len(custom_list_input) != len(available_dest_ids):
            print(f"  ERREUR: L'ordre doit contenir exactement {len(available_dest_ids)} destinations. Attendu: {available_dest_ids}. Réessayez.")
            is_valid_custom = False
        else:
            for d_id in custom_list_input:
                if d_id not in available_dest_ids: print(f"  ERREUR: '{d_id}' invalide (doit être parmi {available_dest_ids}). Réessayez."); is_valid_custom = False; break
                if d_id in seen_in_custom: print(f"  ERREUR: '{d_id}' dupliquée. Réessayez."); is_valid_custom = False; break
                temp_list.append(d_id); seen_in_custom.add(d_id)
        if is_valid_custom: final_custom_list = temp_list
        else:
            retry = input("  Réessayer l'ordre personnalisé? (o/N): ").lower().strip()
            if retry != 'o': return None 
    return final_custom_list

def get_fixed_sort_config_from_user(phase_description, temp_dest_df_for_options):
    print(f"\n--- Configuration du tri FIXE pour : {phase_description} (Heuristique H1) ---")
    print("1. Par 'Objectif QMIN (20%)' décroissant")
    print("2. Par 'Objectif QMIN (20%)' croissant")
    print("3. Par 'Demande Annuelle Totale' décroissante")
    print("4. Par 'Demande Annuelle Totale' croissante")
    print("5. Par 'Distance minimale vers destination' croissante")
    print("6. Par 'Distance minimale vers destination' décroissante")
    print("7. Ordre spécifique que vous allez entrer")
    print("8. Aucun ordre spécifique (défaut interne de H1)")
    sort_config = None; user_choice_valid = False
    
    if temp_dest_df_for_options.empty:
        print(f"AVERTISSEMENT: Aucune destination disponible pour configurer le tri pour '{phase_description}'. Utilisation du défaut (Option 8).")
        return None 

    available_ids = list(temp_dest_df_for_options.index) 
    while not user_choice_valid:
        choice_str = input(f"Votre choix pour '{phase_description}' (1-8) : ").strip()
        if choice_str == '1': sort_config = ('q_min_initial_target_tons', False); user_choice_valid = True
        elif choice_str == '2': sort_config = ('q_min_initial_target_tons', True); user_choice_valid = True
        elif choice_str == '3': sort_config = ('annual_demand_tons', False); user_choice_valid = True
        elif choice_str == '4': sort_config = ('annual_demand_tons', True); user_choice_valid = True
        elif choice_str == '5': sort_config = ('min_distance_km', True); user_choice_valid = True
        elif choice_str == '6': sort_config = ('min_distance_km', False); user_choice_valid = True
        elif choice_str == '7':
            order_list = get_user_custom_order_input(f"l'ordre pour '{phase_description}'", available_ids)
            if order_list is not None: 
                sort_config = ('custom_order', order_list); user_choice_valid = True
            else: print("Aucun ordre personnalisé fourni ou abandonné. Choisissez une autre option ou réessayez (7).")
        elif choice_str == '8': sort_config = None; user_choice_valid = True
        else: print("Choix invalide.")
    print(f"Configuration pour '{phase_description}': {sort_config if sort_config else 'Défaut interne H1'}")
    return sort_config

def get_starting_order_for_optimization(prompt_message, available_dest_ids, temp_dest_df_for_options):
    print(f"\n--- {prompt_message} ---")
    print("Choisissez un ordre de DÉPART pour l'optimisation:")
    print("1. Par 'Objectif QMIN (20%)' décroissant")
    print("2. Par 'Demande Annuelle Totale' décroissante")
    print("3. Par 'Distance minimale vers destination' croissante (plus proche en premier)")
    print("4. Ordre spécifique que vous allez entrer")
    print("5. Aucun ordre spécifique (ordre des données initiales / alphabétique si non trié)")
    start_order_list = None

    if temp_dest_df_for_options.empty and not available_dest_ids:
        print(f"AVERTISSEMENT: Aucune destination disponible pour '{prompt_message}'. Impossible de choisir un ordre de départ.")
        return []

    actual_available_ids = available_dest_ids if available_dest_ids else list(temp_dest_df_for_options.index)
    if not actual_available_ids:
        print(f"AVERTISSEMENT: Aucune destination disponible pour '{prompt_message}'. Impossible de choisir un ordre de départ.")
        return []


    while start_order_list is None:
        choice = input("Votre choix pour l'ordre de départ (1-5): ").strip()
        if choice == '1':
            if 'q_min_initial_target_tons' in temp_dest_df_for_options.columns and not temp_dest_df_for_options.empty:
                 start_order_list = temp_dest_df_for_options.sort_values(by='q_min_initial_target_tons', ascending=False).index.tolist()
            else: print("Erreur/Avertissement: Colonne 'q_min_initial_target_tons' non trouvée ou pas de données pour le tri. Réessayez."); continue
        elif choice == '2':
            if 'annual_demand_tons' in temp_dest_df_for_options.columns and not temp_dest_df_for_options.empty:
                start_order_list = temp_dest_df_for_options.sort_values(by='annual_demand_tons', ascending=False).index.tolist()
            else: print("Erreur/Avertissement: Colonne 'annual_demand_tons' non trouvée ou pas de données pour le tri. Réessayez."); continue
        elif choice == '3':
            if 'min_distance_km' in temp_dest_df_for_options.columns and not temp_dest_df_for_options.empty:
                start_order_list = temp_dest_df_for_options.sort_values(by='min_distance_km', ascending=True).index.tolist()
            else: print("Erreur/Avertissement: Colonne 'min_distance_km' non trouvée ou pas de données pour le tri. Réessayez."); continue
        elif choice == '4':
            start_order_list = get_user_custom_order_input(f"l'ordre de départ pour '{prompt_message}'", actual_available_ids)
            if start_order_list is None: print("Aucun ordre de départ personnalisé fourni ou abandonné. Réessayez."); continue 
        elif choice == '5':
            start_order_list = actual_available_ids[:] 
        else:
            print("Choix invalide. Veuillez réessayer.")
            continue
        if start_order_list is not None : 
            print(f"Ordre de départ choisi pour '{prompt_message}': {start_order_list}")
    return start_order_list if start_order_list is not None else []


# --- Fonction pour écrire les résultats dans Excel ---
def ecrire_resultats_excel(chemin_fichier_excel, nom_feuille_sortie, sim_results,
                           origins_initial_df_ref, destinations_initial_df_ref):
    print(f"\n--- Écriture des Résultats dans Excel ---")
    print(f"Fichier: {chemin_fichier_excel}, Feuille: {nom_feuille_sortie}")
    
    if not sim_results:
        print("Aucun résultat de simulation à écrire.")
        return

    try:
        with pd.ExcelWriter(chemin_fichier_excel, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
            current_row = 0 

            info_sim = f"Résultats Simulation - Profit: {sim_results.get('profit', 0.0):.2f}, " \
                       f"Jours: {sim_results.get('days_taken_simulation_loop', 'N/A')}, " \
                       f"Demande satisfaite: {'Oui' if sim_results.get('all_demand_met', False) else 'Non'}"
            pd.DataFrame([info_sim]).to_excel(writer, sheet_name=nom_feuille_sortie, startrow=current_row, index=False, header=False)
            current_row += 2 

            shipments_df_res = sim_results.get('shipments_df')
            if shipments_df_res is not None and not shipments_df_res.empty:
                print("  - Écriture des expéditions détaillées...")
                pd.DataFrame(["Détail des Expéditions"]).to_excel(writer, sheet_name=nom_feuille_sortie, startrow=current_row, index=False, header=False)
                current_row += 1
                shipments_df_res.to_excel(writer, sheet_name=nom_feuille_sortie, startrow=current_row, index=False, header=True)
                current_row += len(shipments_df_res) + 2 
            else:
                print("  - Aucune expédition à écrire.")
                pd.DataFrame(["Aucune expédition enregistrée"]).to_excel(writer, sheet_name=nom_feuille_sortie, startrow=current_row, index=False, header=False)
                current_row += 2
            
            print("  - Écriture du récapitulatif final par destination...")
            pd.DataFrame(["Récapitulatif Final par Destination (Yj)"]).to_excel(writer, sheet_name=nom_feuille_sortie, startrow=current_row, index=False, header=False)
            current_row +=1
            final_dest_df_res = sim_results.get('final_destinations_df')
            if final_dest_df_res is not None:
                recap_dest_df = final_dest_df_res.copy()
                recap_dest_df_to_write = recap_dest_df.reset_index().rename(columns={'index': 'ID_Destination'})

                recap_dest_df_to_write = recap_dest_df_to_write.rename(
                    columns={'q_min_initial_target_tons': 'Qmin_Cible_Yj', 
                             'q_min_initial_delivered_tons': 'Qmin_Livre_Yj', 
                             'delivered_so_far_tons': 'Total_Livre_Yj', 
                             'remaining_annual_demand_tons': 'Dem_Rest_Yj'}
                )
                if destinations_initial_df_ref is not None and 'annual_demand_tons' in destinations_initial_df_ref.columns:
                    recap_dest_df_to_write = recap_dest_df_to_write.merge(
                        destinations_initial_df_ref[['annual_demand_tons']].rename(columns={'annual_demand_tons':'Dem_Ann_Yj'}),
                        left_on='ID_Destination', right_index=True, how='left'
                    )
                else:
                    recap_dest_df_to_write['Dem_Ann_Yj'] = 'N/A' 
                
                cols_dest = ['ID_Destination', 'Dem_Ann_Yj', 'Qmin_Cible_Yj', 'Qmin_Livre_Yj', 'Total_Livre_Yj', 'Dem_Rest_Yj']
                recap_dest_df_to_write = recap_dest_df_to_write[[col for col in cols_dest if col in recap_dest_df_to_write.columns]]
                recap_dest_df_to_write.round(2).to_excel(writer, sheet_name=nom_feuille_sortie, startrow=current_row, index=False)
                current_row += len(recap_dest_df_to_write) + 2
            else:
                pd.DataFrame(["Données de destination finales non disponibles."]).to_excel(writer, sheet_name=nom_feuille_sortie, startrow=current_row, index=False, header=False)
                current_row += 2

            print("  - Écriture du récapitulatif final par origine...")
            pd.DataFrame(["Récapitulatif Final par Origine (Xi)"]).to_excel(writer, sheet_name=nom_feuille_sortie, startrow=current_row, index=False, header=False)
            current_row += 1
            final_orig_df_res = sim_results.get('final_origins_df')
            if final_orig_df_res is not None:
                recap_orig_df = final_orig_df_res.copy()
                recap_orig_df_to_write = recap_orig_df.reset_index().rename(columns={'index': 'ID_Origine'}) 

                if shipments_df_res is not None and not shipments_df_res.empty:
                    total_expedie_par_xi = shipments_df_res.groupby('origin')['quantity_tons'].sum().rename('Total_Exp_Xi')
                    recap_orig_df_to_write = recap_orig_df_to_write.merge(total_expedie_par_xi, left_on='ID_Origine', right_on='origin', how='left').fillna({'Total_Exp_Xi':0.0})
                    if 'origin' in recap_orig_df_to_write.columns and 'ID_Origine' in recap_orig_df_to_write.columns and 'origin' != 'ID_Origine':
                        recap_orig_df_to_write = recap_orig_df_to_write.drop(columns=['origin'])
                else:
                    recap_orig_df_to_write['Total_Exp_Xi'] = 0.0
                
                recap_orig_df_to_write = recap_orig_df_to_write.rename(columns={'current_available_product_tons': 'Stock_Fin_Xi'})
                if origins_initial_df_ref is not None and 'initial_available_product_tons' in origins_initial_df_ref.columns:
                    recap_orig_df_to_write = recap_orig_df_to_write.merge(
                        origins_initial_df_ref[['initial_available_product_tons']].rename(columns={'initial_available_product_tons':'Stock_Initial_Global_Xi'}),
                        left_on='ID_Origine', right_index=True, how='left'
                    )
                else:
                    recap_orig_df_to_write['Stock_Initial_Global_Xi'] = 'N/A'

                cols_orig = ['ID_Origine', 'Stock_Initial_Global_Xi', 'Total_Exp_Xi', 'Stock_Fin_Xi']
                recap_orig_df_to_write = recap_orig_df_to_write[[col for col in cols_orig if col in recap_orig_df_to_write.columns]]
                recap_orig_df_to_write.round(2).to_excel(writer, sheet_name=nom_feuille_sortie, startrow=current_row, index=False)
                current_row += len(recap_orig_df_to_write) + 2
            else:
                pd.DataFrame(["Données d'origine finales non disponibles."]).to_excel(writer, sheet_name=nom_feuille_sortie, startrow=current_row, index=False, header=False)
                current_row += 2
                
            final_tracking_vars_res = sim_results.get('final_tracking_vars')
            if final_tracking_vars_res:
                print("  - Écriture du suivi quotidien des wagons...")
                pd.DataFrame(["Suivi Quotidien des Wagons"]).to_excel(writer, sheet_name=nom_feuille_sortie, startrow=current_row, index=False, header=False)
                current_row +=1
                daily_wagon_log_df = pd.DataFrame(final_tracking_vars_res.get('daily_wagon_log', []))
                if not daily_wagon_log_df.empty:
                    daily_wagon_log_df.to_excel(writer, sheet_name=nom_feuille_sortie, startrow=current_row, index=False)
                    current_row += len(daily_wagon_log_df) + 2
                else:
                    pd.DataFrame(["Aucun suivi quotidien des wagons à afficher."]).to_excel(writer, sheet_name=nom_feuille_sortie, startrow=current_row, index=False, header=False)
                    current_row += 2

                print("  - Écriture des informations finales sur les wagons...")
                pd.DataFrame(["Informations Finales sur les Wagons"]).to_excel(writer, sheet_name=nom_feuille_sortie, startrow=current_row, index=False, header=False)
                current_row +=1
                wagons_info_list = [
                    {"Information": "Wagons restants disponibles à la fin", "Valeur": final_tracking_vars_res['wagons_available']},
                    {"Information": "Wagons encore en transit à la fin", "Valeur": sum(w['num_wagons'] for w in final_tracking_vars_res['wagons_in_transit'])}
                ]
                pd.DataFrame(wagons_info_list).to_excel(writer, sheet_name=nom_feuille_sortie, startrow=current_row, index=False)
            else:
                 pd.DataFrame(["Données de suivi des wagons non disponibles."]).to_excel(writer, sheet_name=nom_feuille_sortie, startrow=current_row, index=False, header=False)
            
        print(f"Résultats écrits avec succès dans la feuille '{nom_feuille_sortie}' du fichier '{chemin_fichier_excel}'.")

    except Exception as e:
        print(f"ERREUR lors de l'écriture des résultats dans Excel: {e}")
        if "No module named 'openpyxl'" in str(e):
            print("La bibliothèque 'openpyxl' est nécessaire. Veuillez l'installer avec: pip install openpyxl")
        import traceback
        traceback.print_exc()
        print("Veuillez vous assurer que le fichier Excel n'est pas ouvert par une autre application.")

# --- Exécution Principale ---
if __name__ == '__main__':
    pd.set_option('display.width', 200); pd.set_option('display.max_columns', None); pd.set_option('display.max_rows', 500)

    relations_glob, origins_glob, destinations_glob = None, None, None 
    try:
        relations_glob, origins_glob, destinations_glob = load_data_csv(
            FICHIER_CSV_RELATIONS, FICHIER_CSV_ORIGINS, FICHIER_CSV_DESTINATIONS
        )
    except Exception as e: 
        print(f"Arrêt du script suite à une erreur critique lors du chargement des données CSV: {e}")
        exit()

    if origins_glob is None or destinations_glob is None or relations_glob is None:
        print("Une ou plusieurs tables de données n'ont pas pu être chargées depuis les CSV. Arrêt.")
        exit()
        
    available_dest_ids_list = list(destinations_glob.index)
    
    # MODIFICATION: Augmentation significative du nombre de wagons pour une simulation plus complète
    num_wagons_global = 500 

    temp_dest_df_for_options_prep = destinations_glob.copy()
    if 'annual_demand_tons' in temp_dest_df_for_options_prep.columns:
         temp_dest_df_for_options_prep['q_min_initial_target_tons'] = 0.20 * temp_dest_df_for_options_prep['annual_demand_tons']
    else: 
        print("AVERTISSEMENT: Colonne 'annual_demand_tons' manquante pour précalcul q_min_initial_target_tons.")
        temp_dest_df_for_options_prep['q_min_initial_target_tons'] = 0

    if 'distance_km' in relations_glob.columns:
        min_distances_prep = relations_glob.groupby('destination')['distance_km'].min().rename('min_distance_km')
        temp_dest_df_for_options_prep = temp_dest_df_for_options_prep.merge(min_distances_prep, left_index=True, right_index=True, how='left')
        temp_dest_df_for_options_prep['min_distance_km'] = temp_dest_df_for_options_prep['min_distance_km'].fillna(float('inf'))
    else:
        print("AVERTISSEMENT: Colonne 'distance_km' manquante dans les données de relations pour calculer min_distance_km.")
        temp_dest_df_for_options_prep['min_distance_km'] = float('inf')

    print("\n--- Choix de l'Heuristique et de la Configuration ---")
    print("Quelle heuristique souhaitez-vous utiliser ?")
    print("1. Heuristique H1")
    print("2. Heuristique H2")
    heuristique_choice = ""; 
    while heuristique_choice not in ['1', '2']: heuristique_choice = input("Votre choix d'heuristique (1 ou 2): ").strip()

    final_qmin_run_config = None 
    final_phase2_run_config = None
    final_sim_results = None 

    print("\nStratégie de configuration des ordres de priorité des destinations:")
    print(" A. Utiliser des tris fixes ou un ordre personnalisé direct")
    print(f" B. Optimiser les ordres par Montée avec l'Heuristique {'H1' if heuristique_choice == '1' else 'H2'}")
    strategy_choice = ""; 
    while strategy_choice not in ['a', 'b']: strategy_choice = input("Votre choix de stratégie (A ou B): ").lower().strip()

    if strategy_choice == 'a':
        print("\n--- Configuration Manuelle des Ordres ---")
        if heuristique_choice == '1':
            final_qmin_run_config = get_fixed_sort_config_from_user("Ordre QMIN (Commun pour H1)", temp_dest_df_for_options_prep)
            final_phase2_run_config = get_fixed_sort_config_from_user("Ordre Phase 2 pour H1", temp_dest_df_for_options_prep)
        else: 
            final_qmin_run_config = get_user_custom_order_input("Ordre QMIN (Commun pour H2)", available_dest_ids_list)
            final_phase2_run_config = get_user_custom_order_input("Ordre Phase 2 pour H2", available_dest_ids_list)
    
    elif strategy_choice == 'b':
        print(f"\n--- Configuration des Ordres de DÉPART pour l'Optimisation par Montée ({'H1' if heuristique_choice == '1' else 'H2'}) ---")
        start_qmin_list = get_starting_order_for_optimization("l'ordre QMIN de départ", available_dest_ids_list, temp_dest_df_for_options_prep)
        start_phase2_list = get_starting_order_for_optimization("l'ordre Phase 2 de départ", available_dest_ids_list, temp_dest_df_for_options_prep)
        
        if not start_qmin_list or not start_phase2_list: 
            print("Erreur: Ordre de départ valide requis pour QMIN ET Phase 2 pour l'optimisation. Simulation avec défauts.")
        else:
            try: max_iterations_hc = int(input("Nombre maximum d'itérations pour la Montée (défaut: 10): ") or "10")
            except ValueError: print("Entrée invalide, 10 itérations."); max_iterations_hc = 10

            if heuristique_choice == '1':
                start_qmin_config_h1 = ('custom_order', start_qmin_list) 
                start_phase2_config_h1 = ('custom_order', start_phase2_list)
                optimized_configs_h1_tuple = hill_climbing_maximizer_h1(
                    relations_glob, origins_glob, destinations_glob,
                    start_qmin_config_h1, start_phase2_config_h1, num_wagons_global, max_iterations_hc)
                final_qmin_run_config = optimized_configs_h1_tuple[0] 
                final_phase2_run_config = optimized_configs_h1_tuple[2] 
            else: 
                final_qmin_run_config, final_phase2_run_config = hill_climbing_maximizer_h2(
                    relations_glob, origins_glob, destinations_glob,
                    start_qmin_list, start_phase2_list, num_wagons_global, max_iterations_hc)

    print("\n--- Lancement de la Simulation Finale ---")
    
    try:
        if heuristique_choice == '1':
            print(f"Utilisation de l'Heuristique H1.")
            print(f"  Config QMIN (H1): {final_qmin_run_config}")
            print(f"  Config Phase 2 (H1): {final_phase2_run_config}")
            final_sim_results = run_simulation_h1(
                relations_glob, origins_glob, destinations_glob,
                qmin_common_config=final_qmin_run_config,
                phase2_config=final_phase2_run_config,
                num_initial_wagons_param=num_wagons_global, silent_mode=False)
        else: # Heuristique H2
            print(f"Utilisation de l'Heuristique H2.")
            print(f"  Ordre QMIN (H2): {final_qmin_run_config}") 
            print(f"  Ordre Phase 2 (H2): {final_phase2_run_config}")
            final_sim_results = run_simulation_h2(
                relations_glob, origins_glob, destinations_glob,
                qmin_user_priority_order=final_qmin_run_config, 
                standard_shipment_dest_priority_order=final_phase2_run_config, 
                num_initial_wagons_param=num_wagons_global, silent_mode=False)
    except Exception as e:
        print(f"ERREUR PENDANT L'EXÉCUTION DE LA SIMULATION: {e}")
        import traceback
        traceback.print_exc()
        final_sim_results = None 

    if final_sim_results:
        display_results_common(final_sim_results, relations_glob, destinations_glob, origins_glob, 
                               "H1" if heuristique_choice == '1' else "H2")
        # Appel à la fonction d'écriture Excel
        ecrire_resultats_excel(FICHIER_EXCEL_SORTIE, NOM_FEUILLE_EXCEL_RESULTATS, final_sim_results,
                               origins_glob, destinations_glob) 
    else:
        print("Aucun résultat de simulation à afficher ou à écrire.")

    print("\n--- Script terminé ---")