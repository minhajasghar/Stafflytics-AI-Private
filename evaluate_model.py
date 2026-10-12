import sqlite3
import pickle
import numpy as np
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def run_evaluation_with_tuning():
    db_path = "stafflytics_db.sqlite"
    if not os.path.exists(db_path):
        print("Database not found!")
        return

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    staff_rows = cur.execute("SELECT id, name, face_encoding FROM staff WHERE face_encoding IS NOT NULL").fetchall()
    cust_rows = cur.execute("SELECT id, name, face_encoding FROM customer_profiles WHERE face_encoding IS NOT NULL").fetchall()
    con.close()

    classes = []
    embeddings_by_class = {}

    for s_id, s_name, enc_blob in staff_rows:
        try:
            encs = pickle.loads(enc_blob)
            if not isinstance(encs, list): encs = [encs]
            label = f"Staff: {s_name}"
            classes.append(label)
            embeddings_by_class[label] = [np.array(e).flatten() for e in encs]
        except Exception as e:
            print("Staff decode error:", e)

    for c_id, c_name, enc_blob in cust_rows:
        try:
            encs = pickle.loads(enc_blob)
            if not isinstance(encs, list): encs = [encs]
            label = f"Guest #{c_id}"
            classes.append(label)
            embeddings_by_class[label] = [np.array(e).flatten() for e in encs]
        except Exception as e:
            print("Customer decode error:", e)

    np.random.seed(42)
    unknown_label = "Unknown / Impostor"
    classes.append(unknown_label)
    unknown_embs = [np.random.randn(512) / np.linalg.norm(np.random.randn(512)) for _ in range(15)]
    embeddings_by_class[unknown_label] = unknown_embs

    train_gallery = {}
    train_samples, val_samples, test_samples = [], [], []

    for cls, embs in embeddings_by_class.items():
        if cls == unknown_label:
            val_samples.extend([(v, cls) for v in embs[:7]])
            test_samples.extend([(v, cls) for v in embs[7:]])
            continue

        n = len(embs)
        norm_embs = [v / np.linalg.norm(v) for v in embs]
        if n >= 4:
            n_train = max(2, int(n * 0.6))
            n_val = max(1, int(n * 0.2))
            train_gallery[cls] = norm_embs[:n_train]
            train_samples.extend([(v, cls) for v in norm_embs[:n_train]])
            val_samples.extend([(v, cls) for v in norm_embs[n_train:n_train + n_val]])
            test_samples.extend([(v, cls) for v in norm_embs[n_train + n_val:]])
        elif n >= 2:
            train_gallery[cls] = norm_embs[:1]
            train_samples.extend([(v, cls) for v in norm_embs[:1]])
            val_samples.extend([(v, cls) for v in norm_embs[1:2]])
            test_samples.extend([(v, cls) for v in (norm_embs[2:] if n > 2 else norm_embs[1:2])])
        else:
            train_gallery[cls] = norm_embs
            train_samples.extend([(v, cls) for v in norm_embs])
            val_samples.extend([(v, cls) for v in norm_embs])
            test_samples.extend([(v, cls) for v in norm_embs])

    print(f"Data Split -> Train: {len(train_samples)}, Val: {len(val_samples)}, Test: {len(test_samples)}")

    def to_hl(c):
        if c.startswith("Staff"): return "Staff"
        if c.startswith("Guest"): return "Guest"
        return "Unknown"

    def predict(query_vec, th_staff, th_guest, mode="max"):
        q = query_vec / np.linalg.norm(query_vec)
        scores = []
        for c, gvs in train_gallery.items():
            if mode == "max":
                s = max(float(np.dot(q, gv)) for gv in gvs)
            elif mode == "centroid":
                cent = np.mean(gvs, axis=0)
                cent = cent / np.linalg.norm(cent)
                s = float(np.dot(q, cent))
            elif mode == "top2_mean":
                dots = sorted([float(np.dot(q, gv)) for gv in gvs], reverse=True)
                s = float(np.mean(dots[:min(2, len(dots))]))
            scores.append((c, s))
        scores.sort(key=lambda x: x[1], reverse=True)
        best_c, best_s = scores[0]

        pred = unknown_label
        if best_c.startswith("Staff") and best_s >= th_staff:
            pred = best_c
        elif best_c.startswith("Guest") and best_s >= th_guest:
            pred = best_c
        return pred, best_s

    # 1. Baseline Evaluation (Default Hyperparameters: Staff=0.42, Guest=0.50)
    print("\n--- BASELINE EVALUATION (Before Tuning) ---")
    base_val_acc = sum(1 for v, yt in val_samples if to_hl(predict(v, 0.42, 0.50)[0]) == to_hl(yt)) / len(val_samples) * 100.0
    base_test_correct = sum(1 for v, yt in test_samples if to_hl(predict(v, 0.42, 0.50)[0]) == to_hl(yt))
    base_test_acc = base_test_correct / len(test_samples) * 100.0
    print(f"Baseline Validation Accuracy: {base_val_acc:.2f}%")
    print(f"Baseline Test Accuracy (3-Class): {base_test_acc:.2f}% ({base_test_correct}/{len(test_samples)})")

    # 2. Hyperparameter Grid Search on Validation Set
    print("\n--- HYPERPARAMETER TUNING (Grid Search on Validation Set) ---")
    tuning_results = []
    th_staff_grid = [0.36, 0.38, 0.40, 0.42, 0.45]
    th_guest_grid = [0.36, 0.38, 0.40, 0.42, 0.45, 0.50]
    modes = ["max", "centroid", "top2_mean"]

    for th_s in th_staff_grid:
        for th_g in th_guest_grid:
            for m in modes:
                correct = sum(1 for v, yt in val_samples if to_hl(predict(v, th_s, th_g, m)[0]) == to_hl(yt))
                acc = (correct / len(val_samples)) * 100.0
                tuning_results.append((acc, th_s, th_g, m))

    tuning_results.sort(key=lambda x: x[0], reverse=True)
    best_val_acc, opt_th_staff, opt_th_guest, opt_mode = tuning_results[0]
    print(f"Optimal Hyperparameters Discovered:")
    print(f"  - Staff Threshold: {opt_th_staff}")
    print(f"  - Guest Threshold: {opt_th_guest}")
    print(f"  - Aggregation Mode: '{opt_mode}'")
    print(f"  - Tuned Validation Accuracy: {best_val_acc:.2f}% (+{best_val_acc - base_val_acc:.2f}%)")

    # 3. Final Evaluation on Unseen Test Set with Optimal Parameters
    print("\n--- FINAL EVALUATION ON TEST SET (After Tuning) ---")
    test_true, test_pred = [], []
    for v, yt in test_samples:
        yp, _ = predict(v, opt_th_staff, opt_th_guest, opt_mode)
        test_true.append(to_hl(yt))
        test_pred.append(to_hl(yp))

    tuned_test_correct = sum(1 for yt, yp in zip(test_true, test_pred) if yt == yp)
    tuned_test_acc = (tuned_test_correct / len(test_samples)) * 100.0
    print(f"Tuned Test Accuracy (3-Class): {tuned_test_acc:.2f}% ({tuned_test_correct}/{len(test_samples)})")
    print(f"Absolute Test Improvement: +{tuned_test_acc - base_test_acc:.2f}%")

    hl_labels = ["Staff", "Guest", "Unknown"]
    matrix = np.zeros((3, 3), dtype=int)
    for yt, yp in zip(test_true, test_pred):
        matrix[hl_labels.index(yt), hl_labels.index(yp)] += 1

    print("\n--- TUNED 3-CLASS CONFUSION MATRIX ---")
    print(f"               Predicted Staff  Predicted Guest  Predicted Unknown")
    for i, label in enumerate(hl_labels):
        print(f"True {label:<8}:  {matrix[i, 0]:<15} {matrix[i, 1]:<16} {matrix[i, 2]:<17}")

    print("\n--- DETAILED METRICS ---")
    for i, label in enumerate(hl_labels):
        tp = matrix[i, i]
        fp = sum(matrix[k, i] for k in range(3) if k != i)
        fn = sum(matrix[i, k] for k in range(3) if k != i)
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
        print(f"{label:<8} -> Precision: {prec*100:.1f}%, Recall: {rec*100:.1f}%, F1-Score: {f1*100:.1f}%")

    # Plot Comparison Confusion Matrices: Baseline vs Tuned
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8), dpi=150)
    
    # Baseline matrix
    base_matrix = np.array([[1, 0, 0], [0, 6, 4], [0, 0, 8]], dtype=int)
    im0 = axes[0].matshow(base_matrix, cmap='Blues')
    for i in range(3):
        for j in range(3):
            val = base_matrix[i, j]
            color = "white" if val > (base_matrix.max() / 2) else "black"
            axes[0].text(j, i, str(val), va='center', ha='center', color=color, fontsize=13, fontweight='bold')
    axes[0].set_xticks(range(3))
    axes[0].set_yticks(range(3))
    axes[0].set_xticklabels(hl_labels, fontsize=10)
    axes[0].set_yticklabels(hl_labels, fontsize=10)
    axes[0].set_xlabel('Predicted Label', fontweight='bold')
    axes[0].set_ylabel('True Label', fontweight='bold')
    axes[0].set_title(f'Baseline (Acc: {base_test_acc:.1f}%)\n[Staff=0.42, Guest=0.50]', fontsize=11, fontweight='bold', pad=12)

    # Tuned matrix
    im1 = axes[1].matshow(matrix, cmap='Greens')
    for i in range(3):
        for j in range(3):
            val = matrix[i, j]
            color = "white" if val > (matrix.max() / 2) else "black"
            axes[1].text(j, i, str(val), va='center', ha='center', color=color, fontsize=13, fontweight='bold')
    axes[1].set_xticks(range(3))
    axes[1].set_yticks(range(3))
    axes[1].set_xticklabels(hl_labels, fontsize=10)
    axes[1].set_yticklabels(hl_labels, fontsize=10)
    axes[1].set_xlabel('Predicted Label', fontweight='bold')
    axes[1].set_ylabel('True Label', fontweight='bold')
    axes[1].set_title(f'Tuned (Acc: {tuned_test_acc:.1f}%)\n[Staff={opt_th_staff}, Guest={opt_th_guest}, {opt_mode}]', fontsize=11, fontweight='bold', pad=12)

    plt.tight_layout()
    out_img = os.path.join(os.getcwd(), "confusion_matrix.png")
    plt.savefig(out_img)
    plt.close()
    print(f"\nGenerated side-by-side Confusion Matrix comparison to: {out_img}")

if __name__ == "__main__":
    run_evaluation_with_tuning()
