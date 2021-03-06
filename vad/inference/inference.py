import os
import time
from collections import deque

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
import tensorflow as tf
from absl import app, flags

from vad.data_processing.data_iterator import file_iter, split_data
from vad.data_processing.feature_extraction import extract_features
from vad.training.input_pipeline import FEAT_SIZE

flags.DEFINE_string(
    "data_dir", "/home/filippo/datasets/LibriSpeech/", "path to data directory"
)
# DGB
flags.DEFINE_string("data_set",
                    "test-clean",
                    "name of data set being used")
flags.DEFINE_string("model_name",
                    "test-clean",
                    "name of exported model to use -- assumed to be in data_dir/models/model_name/resnet1d/exported")
flags.DEFINE_string("results_dir",
                    "../results/",
                    "name of results directory")
# flags.DEFINE_string(
#     "exported_model",
#     "/home/filippo/datasets/LibriSpeech/tfrecords/models/resnet1d/inference/exported/",
#     "path to pretrained TensorFlow exported model",
# )
# end DGB
flags.DEFINE_integer("seq_len", 1024, "sequence length for speech prediction")
flags.DEFINE_integer("stride", 1, "stride for sliding window prediction")
flags.DEFINE_boolean("smoothing", False, "apply smoothing feature")
FLAGS = flags.FLAGS


def visualize_predictions(signal, fn, preds, sr=16000):
    fig = plt.figure(figsize=(15, 10))
    sns.set()
    ax = fig.add_subplot(1, 1, 1)
    ax.plot([i / sr for i in range(len(signal))], signal)
    for predictions in preds:
        color = "r" if predictions[2] == 0 else "g"
        ax.axvspan((predictions[0]) / sr, predictions[1] / sr, alpha=0.5, color=color)
    plt.title("Prediction on signal {}, speech in green".format(fn), size=20)
    plt.xlabel("Time (s)", size=20)
    plt.ylabel("Amplitude", size=20)
    plt.xticks(size=15)
    plt.yticks(size=15)
    plt.show()


def smooth_predictions(preds):
    smoothed_preds = []
    # Smooth with 3 consecutive windows
    for i in range(2, len(preds), 3):
        cur_pred = preds[i]
        if cur_pred[2] == preds[i - 1][2] == preds[i - 2][2]:
            smoothed_preds.append([preds[i - 2][0], cur_pred[1], cur_pred[2]])
        else:
            if len(smoothed_preds) > 0:
                smoothed_preds.append(
                    [preds[i - 2][0], cur_pred[1], smoothed_preds[-1][2]]
                )
            else:
                smoothed_preds.append([preds[i - 2][0], cur_pred[1], 0.0])
    # Hangover
    n = 0
    while n < len(smoothed_preds):
        cur_pred = smoothed_preds[n]
        if cur_pred[2] == 1:
            if n > 0:
                smoothed_preds[n - 1][2] = 1
            if n < len(smoothed_preds) - 1:
                smoothed_preds[n + 1][2] = 1
            n += 2
        else:
            n += 1
    return smoothed_preds


def main(_):
    np.random.seed(0)

    # Directories
    # DGB
    # data_dir = os.path.join(FLAGS.data_dir, "test-clean/")
    # label_dir = os.path.join(FLAGS.data_dir, "labels/")
    data_dir = os.path.join(FLAGS.data_dir, FLAGS.data_set + "/")
    # Always use the test-clean data set and always use the same labels
    label_dir = os.path.join(FLAGS.data_dir, "labels/test-clean/")
    results_fn = FLAGS.results_dir + "results_model_" + FLAGS.model_name \
        + "_data_" + FLAGS.data_set + "_cm.csv"
    results_file = open(results_fn, "w")
    results_file.write("signal_name, length, matches, checks, pc_accuracy, psas, psan, pnas, pnan\n")
    # end DGB

    _, _, test = split_data(label_dir, split="0.7/0.15", random_seed=0)
    file_it = file_iter(data_dir, label_dir, files=test)

    # TensorFlow inputs
    features_input_ph = tf.placeholder(shape=FEAT_SIZE, dtype=tf.float32)
    features_input_op = tf.transpose(features_input_ph, perm=[1, 0])
    features_input_op = tf.expand_dims(features_input_op, axis=0)

    # TensorFlow exported model
    speech_predictor = tf.contrib.predictor.from_saved_model(
        # DGB
        # export_dir=FLAGS.exported_model
        export_dir=FLAGS.data_dir + "models/" + FLAGS.model_name + "/resnet1d/exported/"
        # end DGB
    )
    init = tf.initializers.global_variables()
    classes = ["Noise", "Speech"]

    # Iterate though test data
    with tf.Session() as sess:
        for signal, labels, fn in file_it:
            sess.run(init)
            print("\nPrediction on file {} ...".format(fn))
            signal_input = deque(signal[: FLAGS.seq_len].tolist(), maxlen=FLAGS.seq_len)

            # DGB
            # Create a vector the same length as the signal vector containing the
            # label data, where at each element, 0 = no speech and 1 = speech.
            matches = 0 # classification = prediction
            psas = 0 # predicted Speech, actual Speech
            psan = 0 # predicted Speech, actual Noise
            pnas = 0 # predicted Noise, actual Speech
            pnan = 0 # predicted Noise, actual Noise
            checks = 0
            truths = np.zeros(len(signal))
            for label in labels:
                for i in range(int(label['start_time']), int(label['end_time'])):
                    truths[i] = 1
            # end DGB

            preds, pred_time = [], []
            pointer = FLAGS.seq_len
            while pointer < len(signal):
                start = time.time()
                # Preprocess signal & extract features
                signal_to_process = np.copy(signal_input)
                signal_to_process = np.float32(signal_to_process)
                features = extract_features(
                    signal_to_process, freq=16000, n_mfcc=5, size=512, step=16
                )

                # Prediction
                features_input = sess.run(
                    features_input_op, feed_dict={features_input_ph: features}
                )
                speech_prob = speech_predictor({"features_input": features_input})[
                    "speech"
                ][0]
                speech_pred = classes[int(np.round(speech_prob))]

                # Time prediction & processing
                end = time.time()
                dt = end - start
                pred_time.append(dt)
                # DGB
                # print(
                #     "Prediction = {} | proba = {:.2f} | time = {:.2f} s".format(
                #         speech_pred, speech_prob[0], dt
                #     )
                # )
                # print(
                #     "Prediction = {} | pointer = {} | proba = {:.2f} | time = {:.2f} s".format(
                #         speech_pred, pointer, speech_prob[0], dt
                #     )
                # )

                # Find the mean of the label truths for the current segment of audio.
                # Round it and compare it to the prediction. Count the matches.
                truth_mean = truths[(pointer - FLAGS.seq_len):(pointer + FLAGS.stride)].mean()
                truth_class = classes[int(np.round(truth_mean))]
                matches += 1 if (truth_class == speech_pred) else 0
                psas += 1 if ((speech_pred == 'Speech') and (truth_class == 'Speech')) else 0
                psan += 1 if ((speech_pred == 'Speech') and (truth_class == 'Noise')) else 0
                pnas += 1 if ((speech_pred == 'Noise') and (truth_class == 'Speech')) else 0
                pnan += 1 if ((speech_pred == 'Noise') and (truth_class == 'Noise')) else 0
                checks += 1
                # print(truth_class)
                # end DGB

                # For visualization
                preds.append([pointer - FLAGS.seq_len, pointer, np.round(speech_prob)])

                # Update signal segment
                signal_input.extend(
                    signal[
                        pointer + FLAGS.stride : pointer + FLAGS.stride + FLAGS.seq_len
                    ]
                )
                pointer += FLAGS.seq_len + FLAGS.stride

            # DGB
            print('Accuracy:', matches, '/', checks, '=', (matches/checks * 100.0), '%',
                  'psas', psas, 'psan', psan, 'pnas', pnas, 'pnan', pnan)
            results_file.write(fn + "," + str(len(signal)) + "," + str(matches) + ","
                               + str(checks) + "," + str(matches/checks * 100.0) + ","
                               + str(psas) + "," + str(psan) + ","
                               + str(pnas) + "," + str(pnan) + "\n")
            results_file.flush()
            # end DGB
            print(
                "Average prediction time = {:.2f} ms".format(np.mean(pred_time) * 1e3)
            )

            # Smoothing & hangover
            if FLAGS.smoothing:
                preds = smooth_predictions(preds)

            # Visualization
            # DGB
            # visualize_predictions(signal, fn, preds)
            # end DGB

    # DGB
    results_file.close()
    # end DGB


if __name__ == "__main__":
    os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"
    tf.logging.set_verbosity(tf.logging.INFO)
    app.run(main)
