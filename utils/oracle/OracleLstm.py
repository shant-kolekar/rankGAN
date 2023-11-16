import tensorflow as tf
from tensorflow.python.ops import tensor_array_ops, control_flow_ops
import numpy as np

class OracleLstm(object):
    def __init__(self, num_vocabulary, batch_size, emb_dim, hidden_dim, sequence_length, start_token, ):
        self.num_vocabulary = num_vocabulary
        self.batch_size = batch_size
        self.emb_dim = emb_dim
        self.hidden_dim = hidden_dim
        self.sequence_length = sequence_length
        self.start_token = tf.constant([start_token] * self.batch_size, dtype=tf.int32)
        self.g_params = []
        self.temperature = 1.0

        with tf.variable_scope('generator'):
            tf.set_random_seed(1234)
            self.g_embeddings = tf.Variable(
                tf.random_normal([self.num_vocabulary, self.emb_dim], 0.0, 1.0, seed=123314154))
            self.g_params.append(self.g_embeddings)
            self.g_recurrent_unit = self.create_recurrent_unit(self.g_params)  # maps h_tm1 to h_t for generator
            self.g_output_unit = self.create_output_unit(self.g_params)  # maps h_t to o_t (output token logits)

        # placeholder definition
        self.x = tf.placeholder(tf.int32, shape=[self.batch_size,
                                                 self.sequence_length])  # sequence of tokens generated by generator

        # processed for batch
        with tf.device("/cpu:0"):
            tf.set_random_seed(1234)
            self.processed_x = tf.transpose(tf.nn.embedding_lookup(self.g_embeddings, self.x),
                                            perm=[1, 0, 2])  # seq_length x batch_size x emb_dim

        # initial states
        self.h0 = tf.zeros([self.batch_size, self.hidden_dim])
        self.h0 = tf.stack([self.h0, self.h0])

        # generator on initial randomness
        gen_o = tensor_array_ops.TensorArray(dtype=tf.float32, size=self.sequence_length,
                                             dynamic_size=False, infer_shape=True)
        gen_x = tensor_array_ops.TensorArray(dtype=tf.int32, size=self.sequence_length,
                                             dynamic_size=False, infer_shape=True)

        def _g_recurrence(i, x_t, h_tm1, gen_o, gen_x):
            h_t = self.g_recurrent_unit(x_t, h_tm1)  # hidden_memory_tuple
            o_t = self.g_output_unit(h_t)  # batch x vocab , logits not prob
            log_prob = tf.log(tf.nn.softmax(o_t))
            next_token = tf.cast(tf.reshape(tf.multinomial(log_prob, 1), [self.batch_size]), tf.int32)
            x_tp1 = tf.nn.embedding_lookup(self.g_embeddings, next_token)  # batch x emb_dim
            gen_o = gen_o.write(i, tf.reduce_sum(
                tf.multiply(tf.one_hot(next_token, self.num_vocabulary, 1.0, 0.0), tf.nn.softmax(o_t)),
                1))  # [batch_size] , prob
            gen_x = gen_x.write(i, next_token)  # indices, batch_size
            return i + 1, x_tp1, h_t, gen_o, gen_x

        _, _, _, self.gen_o, self.gen_x = control_flow_ops.while_loop(
            cond=lambda i, _1, _2, _3, _4: i < self.sequence_length,
            body=_g_recurrence,
            loop_vars=(tf.constant(0, dtype=tf.int32),
                       tf.nn.embedding_lookup(self.g_embeddings, self.start_token), self.h0, gen_o, gen_x)
        )

        self.gen_x = self.gen_x.stack()  # seq_length x batch_size
        self.gen_x = tf.transpose(self.gen_x, perm=[1, 0])  # batch_size x seq_length

        # supervised pretraining for generator
        g_predictions = tensor_array_ops.TensorArray(
            dtype=tf.float32, size=self.sequence_length,
            dynamic_size=False, infer_shape=True)

        ta_emb_x = tensor_array_ops.TensorArray(
            dtype=tf.float32, size=self.sequence_length)
        ta_emb_x = ta_emb_x.unstack(self.processed_x)

        def _pretrain_recurrence(i, x_t, h_tm1, g_predictions):
            h_t = self.g_recurrent_unit(x_t, h_tm1)
            o_t = self.g_output_unit(h_t)
            g_predictions = g_predictions.write(i, tf.nn.softmax(o_t))  # batch x vocab_size
            x_tp1 = ta_emb_x.read(i)
            return i + 1, x_tp1, h_t, g_predictions

        _, _, _, self.g_predictions = control_flow_ops.while_loop(
            cond=lambda i, _1, _2, _3: i < self.sequence_length,
            body=_pretrain_recurrence,
            loop_vars=(tf.constant(0, dtype=tf.int32),
                       tf.nn.embedding_lookup(self.g_embeddings, self.start_token),
                       self.h0, g_predictions))

        self.g_predictions = tf.transpose(
            self.g_predictions.stack(), perm=[1, 0, 2])  # batch_size x seq_length x vocab_size

        # pretraining loss
        self.pretrain_loss = -tf.reduce_sum(
            tf.one_hot(tf.to_int32(tf.reshape(self.x, [-1])), self.num_vocabulary, 1.0, 0.0) * tf.log(
                tf.reshape(self.g_predictions, [-1, self.num_vocabulary]))) / (self.sequence_length * self.batch_size)

        self.out_loss = tf.reduce_sum(
            tf.reshape(
                -tf.reduce_sum(
                    tf.one_hot(tf.to_int32(tf.reshape(self.x, [-1])), self.num_vocabulary, 1.0, 0.0) * tf.log(
                        tf.reshape(self.g_predictions, [-1, self.num_vocabulary])), 1
                ), [-1, self.sequence_length]
            ), 1
        )  # batch_size


        # Compute the similarity between minibatch examples and all embeddings.
        # We use the cosine distance:

    def set_similarity(self, valid_examples=None, pca=True):
        if valid_examples == None:
            if pca:
                valid_examples = np.array(range(20))
            else:
                valid_examples = np.array(range(self.num_vocabulary))
        self.valid_dataset = tf.constant(valid_examples, dtype=tf.int32)
        self.norm = tf.sqrt(tf.reduce_sum(tf.square(self.g_embeddings), 1, keep_dims=True))
        self.normalized_embeddings = self.g_embeddings / self.norm
        # PCA
        if self.num_vocabulary >= 20 and pca == True:
            emb = tf.matmul(self.normalized_embeddings, tf.transpose(self.normalized_embeddings))
            s, u, v = tf.svd(emb)
            u_r = tf.strided_slice(u, begin=[0, 0], end=[20, self.num_vocabulary], strides=[1, 1])
            self.normalized_embeddings = tf.matmul(u_r, self.normalized_embeddings)
        self.valid_embeddings = tf.nn.embedding_lookup(
            self.normalized_embeddings, self.valid_dataset)
        self.similarity = tf.matmul(self.valid_embeddings, tf.transpose(self.normalized_embeddings))

    def generate(self, session):
        # h0 = np.random.normal(size=self.hidden_dim)
        outputs = session.run(self.gen_x)
        return outputs

    def init_matrix(self, shape):
        return tf.random_normal(shape, stddev=1.0, seed=10)

    def create_recurrent_unit(self, params):
        # Weights and Bias for input and hidden tensor
        self.Wi = tf.Variable(tf.random_normal([self.emb_dim, self.hidden_dim], 0.0, 1000000.0, seed=111))
        self.Ui = tf.Variable(tf.random_normal([self.hidden_dim, self.hidden_dim], 0.0, 1000000.0, seed=211))
        self.bi = tf.Variable(tf.random_normal([self.hidden_dim, ], 0.0, 1000000.0, seed=311))

        self.Wf = tf.Variable(tf.random_normal([self.emb_dim, self.hidden_dim], 0.0, 1000000.0, seed=114))
        self.Uf = tf.Variable(tf.random_normal([self.hidden_dim, self.hidden_dim], 0.0, 1000000.0, seed=115))
        self.bf = tf.Variable(tf.random_normal([self.hidden_dim, ], 0.0, 1000000.0, seed=116))

        self.Wog = tf.Variable(tf.random_normal([self.emb_dim, self.hidden_dim], 0.0, 1000000.0, seed=997))
        self.Uog = tf.Variable(tf.random_normal([self.hidden_dim, self.hidden_dim], 0.0, 1000000.0, seed=998))
        self.bog = tf.Variable(tf.random_normal([self.hidden_dim, ], 0.0, 1000000.0, seed=999))

        self.Wc = tf.Variable(tf.random_normal([self.emb_dim, self.hidden_dim], 0.0, 1000000.0, seed=110))
        self.Uc = tf.Variable(tf.random_normal([self.hidden_dim, self.hidden_dim], 0.0, 1000000.0, seed=111))
        self.bc = tf.Variable(tf.random_normal([self.hidden_dim, ], 0.0, 1000000.0, seed=112))
        params.extend([
            self.Wi, self.Ui, self.bi,
            self.Wf, self.Uf, self.bf,
            self.Wog, self.Uog, self.bog,
            self.Wc, self.Uc, self.bc])

        def unit(x, hidden_memory_tm1):
            previous_hidden_state, c_prev = tf.unstack(hidden_memory_tm1)

            # Input Gate
            i = tf.sigmoid(
                tf.matmul(x, self.Wi) +
                tf.matmul(previous_hidden_state, self.Ui) + self.bi
            )

            # Forget Gate
            f = tf.sigmoid(
                tf.matmul(x, self.Wf) +
                tf.matmul(previous_hidden_state, self.Uf) + self.bf
            )

            # Output Gate
            o = tf.sigmoid(
                tf.matmul(x, self.Wog) +
                tf.matmul(previous_hidden_state, self.Uog) + self.bog
            )

            # New Memory Cell
            c_ = tf.nn.tanh(
                tf.matmul(x, self.Wc) +
                tf.matmul(previous_hidden_state, self.Uc) + self.bc
            )

            # Final Memory cell
            c = f * c_prev + i * c_

            # Current Hidden state
            current_hidden_state = o * tf.nn.tanh(c)

            return tf.stack([current_hidden_state, c])

        return unit

    def create_output_unit(self, params):
        self.Wo = tf.Variable(tf.random_normal([self.hidden_dim, self.num_vocabulary], 0.0, 1.0, seed=12341))
        self.bo = tf.Variable(tf.random_normal([self.num_vocabulary], 0.0, 1.0, seed=56865246))
        params.extend([self.Wo, self.bo])

        def unit(hidden_memory_tuple):
            hidden_state, c_prev = tf.unstack(hidden_memory_tuple)
            logits = tf.matmul(hidden_state, self.Wo) + self.bo
            return logits

        return unit

    def set_similarity(self, valid_examples=None, pca=True):
        if valid_examples == None:
            if pca:
                valid_examples = np.array(range(20))
            else:
                valid_examples = np.array(range(self.num_vocabulary))
        self.valid_dataset = tf.constant(valid_examples, dtype=tf.int32)
        self.norm = tf.sqrt(tf.reduce_sum(tf.square(self.g_embeddings), 1, keep_dims=True))
        self.normalized_embeddings = self.g_embeddings / self.norm
        # PCA
        if self.num_vocabulary >= 20 and pca == True:
            emb = tf.matmul(self.normalized_embeddings, tf.transpose(self.normalized_embeddings))
            s, u, v = tf.svd(emb)
            u_r = tf.strided_slice(u, begin=[0, 0], end=[20, self.num_vocabulary], strides=[1, 1])
            self.normalized_embeddings = tf.matmul(u_r, self.normalized_embeddings)
        self.valid_embeddings = tf.nn.embedding_lookup(
            self.normalized_embeddings, self.valid_dataset)
        self.similarity = tf.matmul(self.valid_embeddings, tf.transpose(self.normalized_embeddings))