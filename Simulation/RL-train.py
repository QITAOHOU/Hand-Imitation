import tensorflow as tf
from tensorflow import keras
from tensorflow.keras.callbacks import TensorBoard
from tensorflow.keras.layers import Input,Dense,Conv2D,MaxPooling2D,Flatten
from tensorflow.keras.models import Model
from tensorflow.keras.optimizers import Adam
from tensorflow.keras import backend as K
from tensorflow.keras.applications.mobilenet_v2 import MobileNetV2
import numpy as np
import os
import gym
import pybullet
import cv2
import gym_handOfJustice

hyperparam={
    'clip_val':0.2,
    'critic_dis':0.5,
    'entrophy_beta':0.001,
    'gamma':0.99,
    'lambda':0.65,
    'actor_lr': 1e-4,
    'critic_lr': 1e-3
    }

def advantages(valueS,masks,rewardSA):
    returns=[]
    gae=0
    for i in range(len(rewardSA)-1,-1,-1):  
        delta = rewardSA[i] + hyperparam['gamma']*valueS[i+1]*masks[i] -valueS[i]
        gae = delta + hyperparam['gamma']*hyperparam['lambda']*masks[i]*gae
        returns.append(gae+valueS[i])
    returns=returns[::-1]
    ## Check If THis WOrks

    adv = np.array(returns) - valueS[:-1]
    return returns, ((adv -np.mean(adv))/(np.std(adv)+1e-10))

def ppo_loss_actor(delta,norm_dist):
    def loss(y_true,y_pred):
        action = y_pred
        total_loss= -1*K.log(norm_dist.prob(action))*delta
        return total_loss
    return loss

def ppo_loss_np(old_policy_probs,advantages,rewards,valueS):
    def loss(y_true,y_pred):
        new_policy_probs = y_pred # Check Here also
        ratio = K.exp(K.log(new_policy_probs)- K.log(old_policy_probs) + 1e-10)
        p1 = ratio*advantages
        p2 = K.clip(ratio,min_value= 1-clipping_val,max_value=1+clipping_val)*advantages
        actor_loss = -K.mean(K.minimum(p1,p2))
        critic_loss = K.mean(K.square(rewards - valueS))
        term_al = hyperparam['critic_dis']*critic_loss
        term_b2 = K.log(new_policy_probs + 1e-10)
        term_b = hyperparam['entrophy_beta']*K.mean(-(new_policy_probs*term_b2))
        total_loss = term_a +actor_loss - term_b
        return total_loss
    return loss

def model_actor_image(input_dims, output_dims):
    state_input = Input(shape=input_dims)
    delta = Input(shape=(1,))
    feature_image = MobileNetV2(include_top=False, weights='imagenet')
    for layer in feature_image.layers:
        layer.trainable = False

    x = Flatten(name = 'flatten')(feature_image(state_input))
    x = Dense(512,activation='relu' , name='fc1')(x)
    x = Dense(128,activation='relu' , name='fc2')(x)
    mu = Dense(output_dims[0])(x)
    sigma = Dense(output_dims[0])(x)
    sigma = tf.keras.activations.softplus(sigma)+1e-5
    norm_dist = tf.contrib.distributions.Normal(mu,sigma)
    action_tf_var = tf.squeeze(norm_dist.sample(1),axis=0)
    

    model = Model(inputs=[state_input, delta],
                  outputs=[action_tf_var])
    model.compile(optimizer=Adam(lr=hyperparam['actor_lr']),loss=[ppo_loss_actor(delta,norm_dist)])
    ## This running twice is fine as normal distribution doesnt change but the sampling does for which we have input the delta with the previous sampling it self
    model.summary()
    return model

def model_critic_image(input_dims):
    state_input = Input(shape=input_dims)
    feature_image = MobileNetV2(include_top=False, weights='imagenet')
    for layer in feature_image.layers:
        layer.trainable=False
    x = Flatten(name='flatten')(feature_image(state_input))
    x = Dense(512,activation='relu',name='fc1')(x)
    x = Dense(128,activation='relu',name='fc2')(x)
    Value_function = Dense(1)(x)

    model = Model(inputs=[state_input],outputs=[Value_function])
    model.compile(optimizer=Adam(lr=hyperparam['critic_lr']),loss='mse')
    model.summary()
    return model


tensor_board = TensorBoard(log_dir=os.getcwd()+'\\logs\\Training\\')
strea = cv2.VideoCapture(os.getcwd()+"\\dataset\\%06d.png")
if not strea.isOpened():
    raise Exception("Problem exporting the video stream")
env = gym.make('handOfJustice-v0',cap=strea,epsilon=200)
state_dims = env.observation_space.shape
action_dims = env.action_space.shape

actor_model = model_actor_image(input_dims=state_dims,output_dims=action_dims)
critic_model = model_critic_image(input_dims=state_dims)


best_reward= -10000000000
num_episodes= 50000
episode_history=[]
for episode in range(num_episodes):
    state = env.reset()
    state = state.reshape((1,)+state.shape  )
    reward_total = 0
    step = 0
    done=False
    while not done:
        action = np.squeeze(actor_model.predict([state,np.array([0])],steps=1))
        #print(action)
        for i in range(len(action)):
            action[i] = max(min(action[i],env.action_space.high[i]),env.action_space.low[i])
        next_state,reward,done,_=env.step(np.squeeze(action))
        next_state = next_state.reshape((1,) + next_state.shape )
        step+=1
        reward_total +=reward
        V_of_next_state = critic_model.predict(next_state)
        V_this_state = critic_model.predict(state)
        target = reward + hyperparam['gamma']*np.squeeze(V_of_next_state)
        td_error = target - np.squeeze(V_this_state)
        td_error = np.array([td_error])
        #print(td_error.shape)
        actor_model.fit([state,td_error],[np.zeros((1,action_dims[0]))],callbacks=[tensor_board])## THis step can be done over a batch periodically also
        critic_model.fit([state],[target],callbacks=[tensor_board])
        state=next_state
    episode_history.append(reward_total)
    print("Episode: {}, Number of Steps : {}, Cumulative reward: {:0.2f}".format(
            episode, step, reward_total))
        
    
