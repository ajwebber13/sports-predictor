"""
ensemble_model.py - Culture & Pulse Analytics
Ensemble ML model combining XGBoost, Random Forest, and Logistic Regression.
Trains on historical head-to-head data with team stats as features.

Session 1: Build, train, evaluate
Session 2: Wire into prediction engine

Usage:
  python ensemble_model.py train wnba   # train WNBA model
  python ensemble_model.py train nba    # train NBA model
  python ensemble_model.py train all    # train all sports
  python ensemble_model.py eval wnba    # evaluate model accuracy
  python ensemble_model.py predict wnba "Minnesota Lynx" "Las Vegas Aces"
"""

import os
import pickle
import numpy as np
import pandas as pd
from datetime import datetime
from database import get_conn

# ── MODEL STORAGE ────────────────────────────────────────────────────────
MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
os.makedirs(MODEL_DIR, exist_ok=True)


# ── FEATURE ENGINEERING ──────────────────────────────────────────────────

def get_team_features(team_name: str, sport: str, season: str = None) -> dict:
    """
    Pull all available features for a team from the DB.
    Returns dict of feature values.
    """
    conn = get_conn()
    c    = conn.cursor()

    features = {
        "net_rating":   0.0,
        "pts_per_game": 0.0,
        "pts_allowed":  0.0,
        "win_pct":      0.5,
        "home_win_pct": 0.5,
        "away_win_pct": 0.5,
        "off_rating":   0.0,
        "def_rating":   0.0,
        "pace":         0.0,
        "ts_pct":       0.0,
        "ast_pct":      0.0,
        "tov_pct":      0.0,
    }

    # Team stats
    query = """
        SELECT wins, losses, pts_per_game, pts_allowed, net_rating,
               home_wins, home_losses, away_wins, away_losses
        FROM team_stats
        WHERE sport = ? AND team_name = ?
    """
    params = [sport, team_name]
    if season:
        query += " AND season = ?"
        params.append(season)
    query += " ORDER BY season DESC LIMIT 1"

    c.execute(query, params)
    row = c.fetchone()

    if row:
        total_games  = (row["wins"] or 0) + (row["losses"] or 0)
        home_games   = (row["home_wins"] or 0) + (row["home_losses"] or 0)
        away_games   = (row["away_wins"] or 0) + (row["away_losses"] or 0)

        features["net_rating"]   = row["net_rating"] or 0.0
        features["pts_per_game"] = row["pts_per_game"] or 0.0
        features["pts_allowed"]  = row["pts_allowed"] or 0.0
        features["win_pct"]      = (row["wins"] or 0) / max(total_games, 1)
        features["home_win_pct"] = (row["home_wins"] or 0) / max(home_games, 1)
        features["away_win_pct"] = (row["away_wins"] or 0) / max(away_games, 1)

    # Advanced metrics
    c.execute("""
        SELECT off_rating, def_rating, pace, ts_pct, ast_pct, tov_pct
        FROM advanced_metrics
        WHERE sport = ? AND team_name = ?
        ORDER BY season DESC LIMIT 1
    """, (sport, team_name))
    adv = c.fetchone()

    if adv:
        features["off_rating"] = adv["off_rating"] or 0.0
        features["def_rating"] = adv["def_rating"] or 0.0
        features["pace"]       = adv["pace"] or 0.0
        features["ts_pct"]     = adv["ts_pct"] or 0.0
        features["ast_pct"]    = adv["ast_pct"] or 0.0
        features["tov_pct"]    = adv["tov_pct"] or 0.0

    conn.close()
    return features


def get_h2h_features(home_team: str, away_team: str, sport: str, before_date: str = None) -> dict:
    """Get head-to-head record between two teams.
    head_to_head table does not exist in production (see
    check_head_to_head_freshness.py) — always returns the
    no-data default rather than crashing."""
    return {"h2h_home_win_pct": 0.5, "h2h_games": 0}


def build_feature_vector(home_team: str, away_team: str, sport: str,
                          date: str = None) -> np.ndarray:
    """
    Build complete feature vector for a matchup.
    Returns numpy array of features.
    """
    home_f = get_team_features(home_team, sport)
    away_f = get_team_features(away_team, sport)
    h2h_f  = get_h2h_features(home_team, away_team, sport, before_date=date)

    features = [
        # Net rating differential
        home_f["net_rating"] - away_f["net_rating"],
        # Win % differential
        home_f["win_pct"] - away_f["win_pct"],
        # Scoring differential
        home_f["pts_per_game"] - away_f["pts_per_game"],
        # Defense differential (lower pts allowed is better)
        away_f["pts_allowed"] - home_f["pts_allowed"],
        # Advanced metrics differentials
        home_f["off_rating"] - away_f["off_rating"],
        home_f["def_rating"] - away_f["def_rating"],  # lower is better for def
        home_f["pace"] - away_f["pace"],
        home_f["ts_pct"] - away_f["ts_pct"],
        home_f["ast_pct"] - away_f["ast_pct"],
        away_f["tov_pct"] - home_f["tov_pct"],  # away tov is good for home
        # Home court advantage features
        home_f["home_win_pct"],
        away_f["away_win_pct"],
        # H2H
        h2h_f["h2h_home_win_pct"],
        h2h_f["h2h_games"],
        # Raw team ratings
        home_f["net_rating"],
        away_f["net_rating"],
    ]

    return np.array(features, dtype=float)


FEATURE_NAMES = [
    "net_rating_diff", "win_pct_diff", "pts_diff", "def_diff",
    "off_rating_diff", "def_rating_diff", "pace_diff", "ts_pct_diff",
    "ast_pct_diff", "tov_pct_diff", "home_win_pct", "away_win_pct",
    "h2h_home_win_pct", "h2h_games", "home_net_rating", "away_net_rating",
]


# ── TRAINING DATA ─────────────────────────────────────────────────────────

def build_training_data(sport: str) -> tuple:
    """
    Build X (features) and y (labels) from results history.
    Label: 1 = home team won, 0 = away team won

    Uses `results` instead of the never-created head_to_head table
    (see check_head_to_head_freshness.py). Prediction Engine v2 can
    log up to 3 results rows per game (moneyline/spread/total), so
    this dedupes to one row per (date, sport, game) before training —
    otherwise the same game gets counted 2-3x.
    """
    conn = get_conn()
    c    = conn.cursor()

    c.execute("""
        SELECT DISTINCT date, home_team, away_team, actual_winner
        FROM results
        WHERE sport = ?
        ORDER BY date ASC
    """, (sport,))

    rows = c.fetchall()
    conn.close()

    X = []
    y = []
    skipped = 0

    print(f"  Building features for {len(rows)} {sport.upper()} games...")

    for row in rows:
        try:
            features = build_feature_vector(
                row["home_team"], row["away_team"],
                sport, date=row["date"]
            )

            # Skip if all zeros (no team stats available)
            if np.all(features == 0):
                skipped += 1
                continue

            label = 1 if row["actual_winner"] == row["home_team"] else 0
            X.append(features)
            y.append(label)

        except Exception:
            skipped += 1
            continue

    print(f"  Built {len(X)} training samples ({skipped} skipped)")

    return np.array(X), np.array(y)


# ── MODEL TRAINING ────────────────────────────────────────────────────────

def train_ensemble(sport: str) -> dict:
    """
    Train XGBoost, Random Forest, and Logistic Regression.
    Returns dict of trained models.
    """
    from sklearn.ensemble import RandomForestClassifier, VotingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import train_test_split, cross_val_score
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline
    from sklearn.metrics import accuracy_score, classification_report
    import xgboost as xgb

    print(f"\n{'='*55}")
    print(f"  TRAINING ENSEMBLE MODEL — {sport.upper()}")
    print(f"  {datetime.now().strftime('%B %d, %Y %I:%M %p')}")
    print(f"{'='*55}")

    X, y = build_training_data(sport)

    if len(X) < 50:
        print(f"  Not enough training data ({len(X)} samples). Need 50+.")
        return {}

    # Train/test split — use last 20% as test set
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, shuffle=False
    )

    print(f"\n  Training set: {len(X_train)} games")
    print(f"  Test set:     {len(X_test)} games")
    print(f"  Home win rate: {y.mean():.1%}")

    # ── LOGISTIC REGRESSION ──
    print(f"\n  Training Logistic Regression...")
    lr_pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("model", LogisticRegression(
            C=1.0, max_iter=1000, random_state=42
        ))
    ])
    lr_pipeline.fit(X_train, y_train)
    lr_acc = accuracy_score(y_test, lr_pipeline.predict(X_test))
    lr_cv  = cross_val_score(lr_pipeline, X, y, cv=5, scoring="accuracy").mean()
    print(f"  Test accuracy:  {lr_acc:.1%}")
    print(f"  CV accuracy:    {lr_cv:.1%}")

    # ── RANDOM FOREST ──
    print(f"\n  Training Random Forest...")
    rf_model = RandomForestClassifier(
        n_estimators=200,
        max_depth=8,
        min_samples_split=10,
        random_state=42,
        n_jobs=-1,
    )
    rf_model.fit(X_train, y_train)
    rf_acc = accuracy_score(y_test, rf_model.predict(X_test))
    rf_cv  = cross_val_score(rf_model, X, y, cv=5, scoring="accuracy").mean()
    print(f"  Test accuracy:  {rf_acc:.1%}")
    print(f"  CV accuracy:    {rf_cv:.1%}")

    # Feature importance
    importances = pd.Series(
        rf_model.feature_importances_,
        index=FEATURE_NAMES
    ).sort_values(ascending=False)
    print(f"\n  Top 5 features:")
    for feat, imp in importances.head(5).items():
        print(f"    {feat:<25} {imp:.3f}")

    # ── XGBOOST ──
    print(f"\n  Training XGBoost...")
    xgb_model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        eval_metric="logloss",
        verbosity=0,
    )
    xgb_model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=False,
    )
    xgb_acc = accuracy_score(y_test, xgb_model.predict(X_test))
    xgb_cv  = cross_val_score(xgb_model, X, y, cv=5, scoring="accuracy").mean()
    print(f"  Test accuracy:  {xgb_acc:.1%}")
    print(f"  CV accuracy:    {xgb_cv:.1%}")

    # ── ENSEMBLE ──
    print(f"\n  Building Ensemble (Voting Classifier)...")
    ensemble = VotingClassifier(
        estimators=[
            ("lr",  lr_pipeline),
            ("rf",  rf_model),
            ("xgb", xgb_model),
        ],
        voting="soft",
        weights=[1, 2, 2],  # XGBoost and RF weighted higher
    )
    ensemble.fit(X_train, y_train)
    ens_acc = accuracy_score(y_test, ensemble.predict(X_test))
    ens_cv  = cross_val_score(ensemble, X, y, cv=5, scoring="accuracy").mean()
    print(f"  Test accuracy:  {ens_acc:.1%}")
    print(f"  CV accuracy:    {ens_cv:.1%}")

    # ── SUMMARY ──
    print(f"\n{'─'*55}")
    print(f"  MODEL COMPARISON — {sport.upper()}")
    print(f"{'─'*55}")
    print(f"  {'Model':<25} {'Test Acc':<12} {'CV Acc'}")
    print(f"  {'─'*45}")
    print(f"  {'Logistic Regression':<25} {lr_acc:.1%}{'':>5} {lr_cv:.1%}")
    print(f"  {'Random Forest':<25} {rf_acc:.1%}{'':>5} {rf_cv:.1%}")
    print(f"  {'XGBoost':<25} {xgb_acc:.1%}{'':>5} {xgb_cv:.1%}")
    print(f"  {'Ensemble':<25} {ens_acc:.1%}{'':>5} {ens_cv:.1%}")
    print(f"{'─'*55}")

    # Save models
    models = {
        "lr":       lr_pipeline,
        "rf":       rf_model,
        "xgb":      xgb_model,
        "ensemble": ensemble,
        "sport":    sport,
        "trained_at": datetime.now().isoformat(),
        "training_samples": len(X_train),
        "test_accuracy": ens_acc,
        "cv_accuracy":   ens_cv,
        "feature_names": FEATURE_NAMES,
    }

    model_path = os.path.join(MODEL_DIR, f"{sport}_ensemble.pkl")
    with open(model_path, "wb") as f:
        pickle.dump(models, f)

    print(f"\n  Model saved: {model_path}")
    return models


# ── PREDICTION ────────────────────────────────────────────────────────────

def predict_game(home_team: str, away_team: str, sport: str) -> dict:
    """
    Use trained ensemble to predict a game.
    Returns home win probability.
    """
    model_path = os.path.join(MODEL_DIR, f"{sport}_ensemble.pkl")

    if not os.path.exists(model_path):
        print(f"No trained model for {sport}. Run: python ensemble_model.py train {sport}")
        return {}

    with open(model_path, "rb") as f:
        models = pickle.load(f)

    features = build_feature_vector(home_team, away_team, sport)
    X        = features.reshape(1, -1)

    ensemble = models["ensemble"]
    proba    = ensemble.predict_proba(X)[0]

    # Individual model probabilities
    lr_proba  = models["lr"].predict_proba(X)[0]
    rf_proba  = models["rf"].predict_proba(X)[0]
    xgb_proba = models["xgb"].predict_proba(X)[0]

    return {
        "home_team":        home_team,
        "away_team":        away_team,
        "ensemble_home_prob": round(proba[1] * 100, 1),
        "ensemble_away_prob": round(proba[0] * 100, 1),
        "lr_home_prob":     round(lr_proba[1] * 100, 1),
        "rf_home_prob":     round(rf_proba[1] * 100, 1),
        "xgb_home_prob":    round(xgb_proba[1] * 100, 1),
        "model_agreement":  round(np.std([lr_proba[1], rf_proba[1], xgb_proba[1]]) * 100, 1),
    }


def evaluate_model(sport: str):
    """Print detailed model evaluation."""
    model_path = os.path.join(MODEL_DIR, f"{sport}_ensemble.pkl")

    if not os.path.exists(model_path):
        print(f"No trained model for {sport}.")
        return

    with open(model_path, "rb") as f:
        models = pickle.load(f)

    print(f"\n{'='*55}")
    print(f"  MODEL EVALUATION — {sport.upper()}")
    print(f"{'='*55}")
    print(f"  Trained:   {models['trained_at'][:10]}")
    print(f"  Samples:   {models['training_samples']}")
    print(f"  Test Acc:  {models['test_accuracy']:.1%}")
    print(f"  CV Acc:    {models['cv_accuracy']:.1%}")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()

        if cmd == "train":
            sport = sys.argv[2].lower() if len(sys.argv) > 2 else "wnba"
            if sport == "all":
                for s in ["wnba", "nba", "nfl", "ncaab", "ncaaf"]:
                    train_ensemble(s)
            else:
                train_ensemble(sport)

        elif cmd == "eval":
            sport = sys.argv[2].lower() if len(sys.argv) > 2 else "wnba"
            evaluate_model(sport)

        elif cmd == "predict":
            if len(sys.argv) < 5:
                print("Usage: python ensemble_model.py predict [sport] [home] [away]")
            else:
                sport     = sys.argv[2].lower()
                home_team = sys.argv[3]
                away_team = sys.argv[4]
                result    = predict_game(home_team, away_team, sport)
                if result:
                    print(f"\n{result['away_team']} @ {result['home_team']}")
                    print(f"  Ensemble:  Home {result['ensemble_home_prob']}% | Away {result['ensemble_away_prob']}%")
                    print(f"  LR:        Home {result['lr_home_prob']}%")
                    print(f"  RF:        Home {result['rf_home_prob']}%")
                    print(f"  XGBoost:   Home {result['xgb_home_prob']}%")
                    print(f"  Agreement: {result['model_agreement']}% std dev")
    else:
        print("Usage: python ensemble_model.py [train|eval|predict] [sport] [args]")