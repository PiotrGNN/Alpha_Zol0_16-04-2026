# runner.py – Symulacja klientów FL, aktualizacja modelu globalnego


def run_fl_round(
    clients,
    global_model,
    holdout=None,
    degrade_tol=0.0,
    outlier_sigma=5.0,
    clip_outliers=True,
):
    # Simulate FL round: each client trains, then aggregate
    from fl.training import aggregate_models, train_local_model, apply_gating

    local_models = [train_local_model(client["data"]) for client in clients]
    new_global = aggregate_models(local_models)
    return apply_gating(
        global_model,
        new_global,
        holdout=holdout,
        degrade_tol=degrade_tol,
        outlier_sigma=outlier_sigma,
        clip_outliers=clip_outliers,
    )
