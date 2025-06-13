# Fichier : simulation_logic.py

import pandas as pd
import math
import itertools

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
        relations_df = pd.read_csv(fichier_relations_path, dtype=str)
        relations_df['origin'] = relations_df['origin'].str.strip()
        relations_df['destination'] = relations_df['destination'].str.strip()
        relations_df['distance_km'] = clean_numeric_column(relations_df['distance_km']).astype(float)
        relations_df['profitability'] = clean_numeric_column(relations_df['profitability']).astype(int)
        origins_df_raw = pd.read_csv(fichier_origines_path, dtype=str)
        origins_df_raw['id'] = origins_df_raw['id'].str.strip()
        origins_df_raw['daily_loading_capacity_tons'] = clean_numeric_column(origins_df_raw['daily_loading_capacity_tons']).astype(float)
        origins_df_raw['initial_available_product_tons'] = clean_numeric_column(origins_df_raw['initial_available_product_tons']).astype(float)
        origins_df = origins_df_raw.set_index('id')
        destinations_df_raw = pd.read_csv(fichier_destinations_path, dtype=str)
        destinations_df_raw['id'] = destinations_df_raw['id'].str.strip()
        destinations_df_raw['daily_unloading_capacity_tons'] = clean_numeric_column(destinations_df_raw['daily_unloading_capacity_tons']).astype(float)
        destinations_df_raw['annual_demand_tons'] = clean_numeric_column(destinations_df_raw['annual_demand_tons']).astype(float)
        destinations_df = destinations_df_raw.set_index('id')
        return relations_df, origins_df, destinations_df
    except Exception as e:
        print(f"Erreur CSV: {e}")
        raise

# --- 2. Initialiser les variables de suivi (Commun) ---
def initialize_tracking_variables(origins_df, destinations_df, num_initial_wagons=100):
    origins_df_sim = origins_df.copy()
    destinations_df_sim = destinations_df.copy()
    origins_df_sim['current_available_product_tons'] = origins_df_sim['initial_available_product_tons'].astype(float)
    destinations_df_sim['delivered_so_far_tons'] = 0.0
    destinations_df_sim['remaining_annual_demand_tons'] = destinations_df_sim['annual_demand_tons'].astype(float)
    destinations_df_sim['q_min_initial_target_tons'] = 0.20 * destinations_df_sim['annual_demand_tons']
    destinations_df_sim['q_min_initial_delivered_tons'] = 0.0
    tracking_vars = {'wagons_available': num_initial_wagons, 'wagons_in_transit': [], 'shipments_log': [], 'daily_wagon_log': [] }
    return origins_df_sim, destinations_df_sim, tracking_vars

# --- Fonction utilitaire pour gérer une expédition (Commun) ---
def process_shipment(day_t, origin_id, dest_id, distance_km, desired_qty,
                     origins_df, destinations_df, tracking_vars,
                     origin_daily_loading_cap_remaining, dest_daily_unloading_cap_remaining,
                     log_prefix=""):
    if desired_qty <= EPSILON or desired_qty < MIN_SHIPMENT_FOR_ONE_WAGON_TONS: return 0.0, 0, origin_daily_loading_cap_remaining, dest_daily_unloading_cap_remaining
    if origin_id not in origins_df.index or dest_id not in destinations_df.index: return 0.0, 0, origin_daily_loading_cap_remaining, dest_daily_unloading_cap_remaining
    qty_can_load = min(desired_qty, origin_daily_loading_cap_remaining, origins_df.loc[origin_id, 'current_available_product_tons'])
    qty_can_unload_and_demand = min(desired_qty, dest_daily_unloading_cap_remaining, destinations_df.loc[dest_id, 'remaining_annual_demand_tons'])
    potential_qty_to_ship = min(qty_can_load, qty_can_unload_and_demand)
    if potential_qty_to_ship < MIN_SHIPMENT_FOR_ONE_WAGON_TONS or potential_qty_to_ship <= EPSILON: return 0.0, 0, origin_daily_loading_cap_remaining, dest_daily_unloading_cap_remaining
    wagons_needed_ideal = math.ceil(potential_qty_to_ship / WAGON_CAPACITY_TONS)
    if tracking_vars['wagons_available'] == 0: return 0.0, 0, origin_daily_loading_cap_remaining, dest_daily_unloading_cap_remaining
    wagons_to_use = min(wagons_needed_ideal, tracking_vars['wagons_available'])
    actual_qty_to_ship = min(potential_qty_to_ship, wagons_to_use * WAGON_CAPACITY_TONS)
    if (actual_qty_to_ship < MIN_SHIPMENT_FOR_ONE_WAGON_TONS and actual_qty_to_ship > EPSILON) or actual_qty_to_ship <= EPSILON: return 0.0, 0, origin_daily_loading_cap_remaining, dest_daily_unloading_cap_remaining
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
    tracking_vars['shipments_log'].append({'ship_day': day_t, 'arrival_day': day_of_arrival_at_dest, 'origin': origin_id, 'destination': dest_id, 'quantity_tons': actual_qty_to_ship, 'wagons_used': final_wagons_used, 'type': log_prefix.strip() or "Standard"})
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
def attempt_initial_q_min_delivery_h1(relations_df, origins_df, destinations_df, tracking_vars, dest_sort_config=None, silent_mode=False):
    day_for_q_min_shipments = 1; q_min_origin_caps = origins_df['daily_loading_capacity_tons'].copy(); q_min_dest_caps = destinations_df['daily_unloading_capacity_tons'].copy()
    iterator = get_destination_iterator_h1(destinations_df, dest_sort_config)
    if iterator is None: iterator = destinations_df.sort_values(by='q_min_initial_target_tons', ascending=False).index.tolist()
    for dest_id in iterator:
        if dest_id not in destinations_df.index: continue
        needed = destinations_df.loc[dest_id, 'q_min_initial_target_tons'] - destinations_df.loc[dest_id, 'q_min_initial_delivered_tons']
        if needed <= EPSILON: continue
        possible_rels = relations_df[relations_df['destination'] == dest_id].copy().merge(origins_df[['current_available_product_tons']], left_on='origin', right_index=True).sort_values(by='current_available_product_tons', ascending=False)
        for _, rel in possible_rels.iterrows():
            orig_id, dist_km = rel['origin'], rel['distance_km']
            if needed <= EPSILON: break
            if orig_id not in origins_df.index: continue
            if q_min_origin_caps.get(orig_id,0) <= EPSILON or q_min_dest_caps.get(dest_id,0) <= EPSILON or origins_df.loc[orig_id, 'current_available_product_tons'] <= EPSILON: continue
            shipped, wagons_used, new_orig_cap, new_dest_cap = process_shipment(day_for_q_min_shipments, orig_id, dest_id, dist_km, needed, origins_df, destinations_df, tracking_vars, q_min_origin_caps[orig_id], q_min_dest_caps[dest_id], "[QMIN_INIT_J1_H1]")
            if shipped > EPSILON: q_min_origin_caps[orig_id], q_min_dest_caps[dest_id] = new_orig_cap, new_dest_cap; destinations_df.loc[dest_id, 'q_min_initial_delivered_tons'] += shipped; needed -= shipped
    return origins_df, destinations_df, tracking_vars, q_min_origin_caps, q_min_dest_caps

def filter_profitable_relations_h1(relations_df):
    return relations_df[relations_df['profitability'] == 1].copy()

# MODIFICATION : Ajout du paramètre `_internal_call_copy` pour la gestion mémoire
def run_simulation_h1(relations_input_df, origins_input_df, destinations_input_df,
                      qmin_common_config=None, phase2_config=None,
                      num_initial_wagons_param=500, silent_mode=False,
                      _internal_call_copy=True):
    if _internal_call_copy:
        relations_df = relations_input_df.copy()
        origins_df_sim_base = origins_input_df.copy()
        destinations_df_sim_base = destinations_input_df.copy()
    else:
        relations_df = relations_input_df
        origins_df_sim_base = origins_input_df
        destinations_df_sim_base = destinations_input_df
    origins_df, destinations_df, tracking_vars_sim = initialize_tracking_variables(origins_df_sim_base, destinations_df_sim_base, num_initial_wagons_param)
    origins_df, destinations_df, tracking_vars_sim, rem_load_d1, rem_unload_d1 = attempt_initial_q_min_delivery_h1(relations_df, origins_df, destinations_df, tracking_vars_sim, qmin_common_config, silent_mode)
    profitable_relations_df = filter_profitable_relations_h1(relations_df)
    all_total_dem_met = False; last_day_of_shipment = 0; day_t = 0
    for day_t_loop in range(1, MAX_SIMULATION_DAYS + 1):
        day_t = day_t_loop
        wagons_shipped_this_day = 0; returned_wagons = 0; active_transit = []
        for ti in tracking_vars_sim['wagons_in_transit']:
            if ti['return_day'] == day_t: returned_wagons += ti['num_wagons']
            elif ti['return_day'] > day_t: active_transit.append(ti)
        wagons_available_at_start = tracking_vars_sim['wagons_available'] + returned_wagons
        tracking_vars_sim['wagons_available'] = wagons_available_at_start; tracking_vars_sim['wagons_in_transit'] = active_transit
        curr_orig_load = rem_load_d1.copy() if day_t == 1 else origins_df['daily_loading_capacity_tons'].copy()
        curr_dest_unload = rem_unload_d1.copy() if day_t == 1 else destinations_df['daily_unloading_capacity_tons'].copy()
        shipments_today = False
        qmin_daily_iter = get_destination_iterator_h1(destinations_df, qmin_common_config)
        if qmin_daily_iter is None: qmin_daily_iter = destinations_df.sort_values(by='q_min_initial_target_tons', ascending=False).index.tolist()
        for dest_id in qmin_daily_iter:
            if dest_id not in destinations_df.index: continue
            needed = destinations_df.loc[dest_id, 'q_min_initial_target_tons'] - destinations_df.loc[dest_id, 'q_min_initial_delivered_tons']
            if needed <= EPSILON: continue
            rels_for_qmin = relations_df[relations_df['destination'] == dest_id].copy().merge(origins_df[['current_available_product_tons']], left_on='origin', right_index=True).sort_values(by='current_available_product_tons', ascending=False)
            for _, rel in rels_for_qmin.iterrows():
                orig_id, dist_km = rel['origin'], rel['distance_km']
                if needed <= EPSILON: break
                if orig_id not in origins_df.index: continue
                if curr_orig_load.get(orig_id,0) <= EPSILON or curr_dest_unload.get(dest_id,0) <= EPSILON or origins_df.loc[orig_id, 'current_available_product_tons'] <= EPSILON: continue
                shipped, wagons_used, n_orig_cap, n_dest_cap = process_shipment(day_t, orig_id, dest_id, dist_km, needed, origins_df, destinations_df, tracking_vars_sim, curr_orig_load[orig_id], curr_dest_unload[dest_id], "[QMIN_DAILY_H1]")
                if shipped > EPSILON: wagons_shipped_this_day += wagons_used; curr_orig_load[orig_id], curr_dest_unload[dest_id] = n_orig_cap, n_dest_cap; destinations_df.loc[dest_id, 'q_min_initial_delivered_tons'] += shipped; needed -= shipped; shipments_today = True; last_day_of_shipment = day_t
        sorted_origins = origins_df.sort_values(by='current_available_product_tons', ascending=False).index
        for orig_id in sorted_origins:
            if orig_id not in origins_df.index: continue
            if origins_df.loc[orig_id, 'current_available_product_tons'] <= EPSILON or curr_orig_load.get(orig_id,0) <= EPSILON: continue
            rels_from_orig = profitable_relations_df[profitable_relations_df['origin'] == orig_id].copy()
            if rels_from_orig.empty: continue
            dest_ids_for_orig = [d_id for d_id in rels_from_orig['destination'].unique() if d_id in destinations_df.index]
            if not dest_ids_for_orig: continue
            temp_dest_df = destinations_df.loc[dest_ids_for_orig].copy()
            phase2_iter = get_destination_iterator_h1(temp_dest_df, phase2_config)
            relation_iterator_data = []
            if phase2_iter is None: relation_iterator_data = rels_from_orig[rels_from_orig['destination'].isin(dest_ids_for_orig)].merge(destinations_df[['remaining_annual_demand_tons']], left_on='destination', right_index=True).sort_values(by='remaining_annual_demand_tons', ascending=False).iterrows()
            else: ordered_rels = [row for dest_id_ord in phase2_iter for _, row in rels_from_orig[rels_from_orig['destination'] == dest_id_ord].iterrows()]; relation_iterator_data = [(idx, series) for idx, series in enumerate(ordered_rels)]
            for _, rel_data in relation_iterator_data:
                dest_id, dist_km = rel_data['destination'], rel_data['distance_km']
                if dest_id not in destinations_df.index or destinations_df.loc[dest_id, 'q_min_initial_delivered_tons'] < (destinations_df.loc[dest_id, 'q_min_initial_target_tons'] - EPSILON): continue
                if curr_orig_load.get(orig_id,0) <= EPSILON or (tracking_vars_sim['wagons_available'] == 0 and dist_km > 0): break
                if destinations_df.loc[dest_id, 'remaining_annual_demand_tons'] <= EPSILON or curr_dest_unload.get(dest_id,0) <= EPSILON: continue
                desired_qty = destinations_df.loc[dest_id, 'remaining_annual_demand_tons']
                if desired_qty <= EPSILON: continue
                shipped, wagons_used, n_orig_cap, n_dest_cap = process_shipment(day_t, orig_id, dest_id, dist_km, desired_qty, origins_df, destinations_df, tracking_vars_sim, curr_orig_load[orig_id], curr_dest_unload[dest_id], "[SIM_PROFIT_H1]")
                if shipped > EPSILON: wagons_shipped_this_day += wagons_used; curr_orig_load[orig_id], curr_dest_unload[dest_id] = n_orig_cap, n_dest_cap; shipments_today = True; last_day_of_shipment = day_t
        tracking_vars_sim['daily_wagon_log'].append({'day': day_t, 'available_start': wagons_available_at_start, 'returned': returned_wagons, 'sent': wagons_shipped_this_day, 'available_end': tracking_vars_sim['wagons_available'], 'in_transit_end': sum(w['num_wagons'] for w in tracking_vars_sim['wagons_in_transit'])})
        all_total_dem_met = (destinations_df['remaining_annual_demand_tons'] <= EPSILON).all()
        if all_total_dem_met or (not shipments_today and (tracking_vars_sim['wagons_available'] == 0 and not tracking_vars_sim['wagons_in_transit'])): break
    shipments_summary_df = pd.DataFrame(tracking_vars_sim['shipments_log'])
    profit_metric = 0.0
    if not shipments_summary_df.empty:
        temp_df = shipments_summary_df.copy().merge(relations_input_df[['origin', 'destination', 'distance_km']], on=['origin', 'destination'], how='left').fillna({'distance_km': 0})
        profit_metric = (temp_df['quantity_tons'] * temp_df['distance_km']).sum()
    return {"profit": profit_metric, "shipments_df": shipments_summary_df, "final_origins_df": origins_df, "final_destinations_df": destinations_df, "final_tracking_vars": tracking_vars_sim, "all_demand_met": all_total_dem_met, "days_taken_simulation_loop": day_t}

# MODIFICATION : Ajout du paramètre `_internal_call_copy` pour la gestion mémoire
def run_simulation_h2(relations_input_df, origins_input_df, destinations_input_df,
                      qmin_user_priority_order=None, standard_shipment_dest_priority_order=None,
                      num_initial_wagons_param=50, silent_mode=False, _internal_call_copy=True):
    if _internal_call_copy:
        relations_df = relations_input_df.copy()
        origins_df_sim_base = origins_input_df.copy()
        destinations_df_sim_base = destinations_input_df.copy()
    else:
        relations_df = relations_input_df
        origins_df_sim_base = origins_input_df
        destinations_df_sim_base = destinations_input_df
    origins_df, destinations_df, tracking_vars_sim = initialize_tracking_variables(origins_df_sim_base, destinations_df_sim_base, num_initial_wagons_param)
    qmin_config_for_attempt = ('custom_order', qmin_user_priority_order) if qmin_user_priority_order else None
    origins_df, destinations_df, tracking_vars_sim, rem_load_d1, rem_unload_d1 = attempt_initial_q_min_delivery_h1(relations_df, origins_df, destinations_df, tracking_vars_sim, qmin_config_for_attempt, silent_mode) 
    profitable_relations_df = filter_profitable_relations_h1(relations_df)
    all_total_dem_met = False; last_day_of_shipment = 0; day_t = 0
    for day_t_loop in range(1, MAX_SIMULATION_DAYS + 1):
        day_t = day_t_loop
        wagons_shipped_this_day = 0; returned_wagons = 0; active_transit = []
        for ti in tracking_vars_sim['wagons_in_transit']:
            if ti['return_day'] == day_t: returned_wagons += ti['num_wagons']
            elif ti['return_day'] > day_t: active_transit.append(ti)
        wagons_available_at_start = tracking_vars_sim['wagons_available'] + returned_wagons
        tracking_vars_sim['wagons_available'] = wagons_available_at_start; tracking_vars_sim['wagons_in_transit'] = active_transit
        curr_orig_load = rem_load_d1.copy() if day_t == 1 else origins_df['daily_loading_capacity_tons'].copy()
        curr_dest_unload = rem_unload_d1.copy() if day_t == 1 else destinations_df['daily_unloading_capacity_tons'].copy()
        shipments_today = False
        qmin_daily_iter_h2 = [dest_id for dest_id in (qmin_user_priority_order or []) if dest_id in destinations_df.index]
        if not qmin_daily_iter_h2: qmin_daily_iter_h2 = destinations_df.sort_values(by='q_min_initial_target_tons', ascending=False).index.tolist()
        for dest_id in qmin_daily_iter_h2:
            if dest_id not in destinations_df.index: continue
            needed = destinations_df.loc[dest_id, 'q_min_initial_target_tons'] - destinations_df.loc[dest_id, 'q_min_initial_delivered_tons']
            if needed <= EPSILON: continue
            rels_for_qmin = relations_df[relations_df['destination'] == dest_id].copy().merge(origins_df[['current_available_product_tons']], left_on='origin', right_index=True).sort_values(by='current_available_product_tons', ascending=False)
            for _, rel in rels_for_qmin.iterrows():
                orig_id, dist_km = rel['origin'], rel['distance_km']
                if needed <= EPSILON: break
                if orig_id not in origins_df.index: continue
                if curr_orig_load.get(orig_id,0) <= EPSILON or curr_dest_unload.get(dest_id,0) <= EPSILON or origins_df.loc[orig_id, 'current_available_product_tons'] <= EPSILON: continue
                shipped, wagons_used, n_orig_cap, n_dest_cap = process_shipment(day_t, orig_id, dest_id, dist_km, needed, origins_df, destinations_df, tracking_vars_sim, curr_orig_load[orig_id], curr_dest_unload[dest_id], "[QMIN_DAILY_H2]")
                if shipped > EPSILON: wagons_shipped_this_day += wagons_used; curr_orig_load[orig_id], curr_dest_unload[dest_id] = n_orig_cap, n_dest_cap; destinations_df.loc[dest_id, 'q_min_initial_delivered_tons'] += shipped; needed -= shipped; shipments_today = True; last_day_of_shipment = day_t
        phase2_dest_iter_h2 = [dest_id for dest_id in (standard_shipment_dest_priority_order or []) if dest_id in destinations_df.index and destinations_df.loc[dest_id, 'remaining_annual_demand_tons'] > EPSILON]
        if not phase2_dest_iter_h2: phase2_dest_iter_h2 = destinations_df[destinations_df['remaining_annual_demand_tons'] > EPSILON].sort_values(by='remaining_annual_demand_tons', ascending=False).index
        for dest_id in phase2_dest_iter_h2:
            if dest_id not in destinations_df.index or destinations_df.loc[dest_id, 'q_min_initial_delivered_tons'] < (destinations_df.loc[dest_id, 'q_min_initial_target_tons'] - EPSILON) or curr_dest_unload.get(dest_id, 0) <= EPSILON or destinations_df.loc[dest_id, 'remaining_annual_demand_tons'] <= EPSILON: continue
            best_origin_for_dest = None; best_origin_dist_km = 0; max_rentabilite_metric = -1.0
            candidate_relations = profitable_relations_df[profitable_relations_df['destination'] == dest_id]
            for _, rel in candidate_relations.iterrows():
                orig_id, dist_km = rel['origin'], rel['distance_km']
                if orig_id not in origins_df.index or origins_df.loc[orig_id, 'current_available_product_tons'] <= EPSILON or curr_orig_load.get(orig_id, 0) <= EPSILON: continue
                if tracking_vars_sim['wagons_available'] == 0 and dist_km > 0: continue
                potential_qty = min(origins_df.loc[orig_id, 'current_available_product_tons'], curr_orig_load.get(orig_id, 0), curr_dest_unload.get(dest_id, 0), destinations_df.loc[dest_id, 'remaining_annual_demand_tons'])
                if potential_qty < MIN_SHIPMENT_FOR_ONE_WAGON_TONS: continue
                current_rentabilite_metric = potential_qty * dist_km 
                if current_rentabilite_metric > max_rentabilite_metric: max_rentabilite_metric = current_rentabilite_metric; best_origin_for_dest = orig_id; best_origin_dist_km = dist_km
            if best_origin_for_dest is not None and max_rentabilite_metric >= 0 :
                desired_std_qty = destinations_df.loc[dest_id, 'remaining_annual_demand_tons']
                shipped_qty, wagons_used, n_orig_cap, n_dest_cap = process_shipment(day_t, best_origin_for_dest, dest_id, best_origin_dist_km, desired_std_qty, origins_df, destinations_df, tracking_vars_sim, curr_orig_load[best_origin_for_dest], curr_dest_unload[dest_id], log_prefix="[SIM_PROFIT_H2]")
                if shipped_qty > EPSILON: wagons_shipped_this_day += wagons_used; curr_orig_load[best_origin_for_dest] = n_orig_cap; curr_dest_unload[dest_id] = n_dest_cap; shipments_today = True
        tracking_vars_sim['daily_wagon_log'].append({'day': day_t, 'available_start': wagons_available_at_start, 'returned': returned_wagons, 'sent': wagons_shipped_this_day, 'available_end': tracking_vars_sim['wagons_available'], 'in_transit_end': sum(w['num_wagons'] for w in tracking_vars_sim['wagons_in_transit'])})
        all_total_dem_met = (destinations_df['remaining_annual_demand_tons'] <= EPSILON).all()
        if all_total_dem_met or (not shipments_today and (tracking_vars_sim['wagons_available'] == 0 and not tracking_vars_sim['wagons_in_transit'])): break
    shipments_summary_df = pd.DataFrame(tracking_vars_sim['shipments_log'])
    profit_metric = 0.0
    if not shipments_summary_df.empty:
        temp_df = shipments_summary_df.copy().merge(relations_input_df[['origin', 'destination', 'distance_km']], on=['origin', 'destination'], how='left').fillna({'distance_km': 0})
        profit_metric = (temp_df['quantity_tons'] * temp_df['distance_km']).sum()
    return {"profit": profit_metric, "shipments_df": shipments_summary_df, "final_origins_df": origins_df, "final_destinations_df": destinations_df, "final_tracking_vars": tracking_vars_sim, "all_demand_met": all_total_dem_met, "days_taken_simulation_loop": day_t}

def generate_custom_order_neighbors(current_custom_order_list):
    neighbors = []; n = len(current_custom_order_list)
    if n >= 2:
        for i in range(n):
            for j in range(i + 1, n):
                neighbor_order = current_custom_order_list[:]; neighbor_order[i], neighbor_order[j] = neighbor_order[j], neighbor_order[i]
                neighbors.append(neighbor_order)
    return neighbors

# MODIFICATION : APPELS OPTIMISÉS DANS HILL CLIMBING
def hill_climbing_maximizer_h1(rels_df_hc, orig_df_hc, dest_df_hc, 
                               initial_qmin_config_tuple, initial_phase2_config_tuple, 
                               num_initial_wagons, max_iterations=10):
    current_best_qmin_cfg = initial_qmin_config_tuple
    current_best_phase2_cfg = initial_phase2_config_tuple
    eval_result = run_simulation_h1(rels_df_hc, orig_df_hc.copy(), dest_df_hc.copy(), current_best_qmin_cfg, current_best_phase2_cfg, num_initial_wagons, True, _internal_call_copy=False)
    current_best_profit_overall = eval_result['profit']
    print(f"\nProfit initial pour l'optimisation (H1): {current_best_profit_overall:.2f}")
    for iteration in range(max_iterations):
        print(f"\n--- Itération de Montée H1 {iteration + 1}/{max_iterations} ---")
        made_improvement = False
        if current_best_qmin_cfg and current_best_qmin_cfg[0] == 'custom_order' and len(current_best_qmin_cfg[1]) >= 2:
            for neighbor_qmin_list in generate_custom_order_neighbors(current_best_qmin_cfg[1]):
                neighbor_qmin_cfg = ('custom_order', neighbor_qmin_list)
                eval_n = run_simulation_h1(rels_df_hc, orig_df_hc.copy(), dest_df_hc.copy(), neighbor_qmin_cfg, current_best_phase2_cfg, num_initial_wagons, True, _internal_call_copy=False)
                if eval_n['profit'] > current_best_profit_overall:
                    current_best_profit_overall = eval_n['profit']; current_best_qmin_cfg = neighbor_qmin_cfg; made_improvement = True
        if current_best_phase2_cfg and current_best_phase2_cfg[0] == 'custom_order' and len(current_best_phase2_cfg[1]) >= 2:
            for neighbor_ph2_list in generate_custom_order_neighbors(current_best_phase2_cfg[1]):
                neighbor_ph2_cfg = ('custom_order', neighbor_ph2_list)
                eval_n = run_simulation_h1(rels_df_hc, orig_df_hc.copy(), dest_df_hc.copy(), current_best_qmin_cfg, neighbor_ph2_cfg, num_initial_wagons, True, _internal_call_copy=False)
                if eval_n['profit'] > current_best_profit_overall:
                    current_best_profit_overall = eval_n['profit']; current_best_phase2_cfg = neighbor_ph2_cfg; made_improvement = True
        if not made_improvement: print("Aucune amélioration trouvée."); break
    print(f"\n--- Fin de l'Optimisation H1. Meilleur profit: {current_best_profit_overall:.2f} ---")
    return (current_best_qmin_cfg, current_best_qmin_cfg, current_best_phase2_cfg)

# MODIFICATION : APPELS OPTIMISÉS DANS HILL CLIMBING
def hill_climbing_maximizer_h2(rels_df_hc, orig_df_hc, dest_df_hc,
                               initial_qmin_order_list, initial_phase2_order_list, 
                               num_initial_wagons, max_iterations=10):
    current_best_qmin_order = initial_qmin_order_list
    current_best_phase2_order = initial_phase2_order_list
    eval_result = run_simulation_h2(rels_df_hc, orig_df_hc.copy(), dest_df_hc.copy(), current_best_qmin_order, current_best_phase2_order, num_initial_wagons, True, _internal_call_copy=False)
    current_best_profit_overall = eval_result['profit']
    print(f"\nProfit initial pour l'optimisation (H2): {current_best_profit_overall:.2f}")
    for iteration in range(max_iterations):
        print(f"\n--- Itération de Montée H2 {iteration + 1}/{max_iterations} ---")
        made_improvement = False
        if current_best_qmin_order and len(current_best_qmin_order) >= 2:
            for neighbor_qmin_list in generate_custom_order_neighbors(current_best_qmin_order):
                eval_n = run_simulation_h2(rels_df_hc, orig_df_hc.copy(), dest_df_hc.copy(), neighbor_qmin_list, current_best_phase2_order, num_initial_wagons, True, _internal_call_copy=False)
                if eval_n['profit'] > current_best_profit_overall:
                    current_best_profit_overall = eval_n['profit']; current_best_qmin_order = neighbor_qmin_list; made_improvement = True
        if current_best_phase2_order and len(current_best_phase2_order) >= 2:
            for neighbor_ph2_list in generate_custom_order_neighbors(current_best_phase2_order):
                eval_n = run_simulation_h2(rels_df_hc, orig_df_hc.copy(), dest_df_hc.copy(), current_best_qmin_order, neighbor_ph2_list, num_initial_wagons, True, _internal_call_copy=False)
                if eval_n['profit'] > current_best_profit_overall:
                    current_best_profit_overall = eval_n['profit']; current_best_phase2_order = neighbor_ph2_list; made_improvement = True
        if not made_improvement: print("Aucune amélioration trouvée."); break
    print(f"\n--- Fin de l'Optimisation H2. Meilleur profit: {current_best_profit_overall:.2f} ---")
    return (current_best_qmin_order, current_best_phase2_order)

def ecrire_resultats_excel(chemin_fichier_excel, nom_feuille_sortie, sim_results,
                           origins_initial_df_ref, destinations_initial_df_ref):
    # Cette fonction est conservée pour la compatibilité
    pass

        
    
    
     
        

        
       
          
              
        
      
        
