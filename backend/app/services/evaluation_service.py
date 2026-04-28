from collections import defaultdict


def evaluate_model(model, dataset):
    preds = model.predict(dataset)

    # ground truth + predictions assumed structured like:
    # dataset = [{"text": ..., "labels": [...]}, ...]
    # preds   = [{"labels": [...]}, ...]

    tp = defaultdict(int)
    fp = defaultdict(int)
    fn = defaultdict(int)

    for gold, pred in zip(dataset, preds):
        gold_labels = set(gold["labels"])
        pred_labels = set(pred["labels"])

        for label in pred_labels:
            if label in gold_labels:
                tp[label] += 1
            else:
                fp[label] += 1

        for label in gold_labels:
            if label not in pred_labels:
                fn[label] += 1

    precision_per_label = {}
    recall_per_label = {}
    f1_per_label = {}

    for label in set(list(tp.keys()) + list(fp.keys()) + list(fn.keys())):
        p = tp[label] / (tp[label] + fp[label] + 1e-8)
        r = tp[label] / (tp[label] + fn[label] + 1e-8)
        f1 = 2 * p * r / (p + r + 1e-8)

        precision_per_label[label] = p
        recall_per_label[label] = r
        f1_per_label[label] = f1

    return {
        "precision": precision_per_label,
        "recall": recall_per_label,
        "f1": f1_per_label,
    }