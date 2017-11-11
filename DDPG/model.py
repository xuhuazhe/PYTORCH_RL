import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from torch.autograd import Variable
import torchvision.transforms as T


import numpy as np

import copy
import logging
bashlogger = logging.getLogger("bash logger")
bashlogger.setLevel(logging.DEBUG)
FORMAT = '[%(asctime)-15s][%(threadName)s][%(levelname)s][%(funcName)s] %(message)s'
logging.basicConfig(format=FORMAT)


from NN import ActorCriticNN
from utils.utils import soft_update, hard_update, OrnsteinUhlenbeckNoise
from utils.replayBuffer import TransitionPR

TAU = 1e-3
GAMMA = 0.99
LR = 1e-3
USE_CUDA = True
BATCH_SIZE = 256


class Model :
	def __init__(self, NN, memory, algo='ddpg',GAMMA=GAMMA,LR=LR,TAU=TAU,use_cuda=USE_CUDA,BATCH_SIZE=BATCH_SIZE ) :
		self.NN = NN
		self.target_NN = copy.deepcopy(NN)
		
		self.use_cuda = use_cuda
		if self.use_cuda :
			self.NN = self.NN.cuda()
			self.target_NN = self.target_NN.cuda()

		self.memory = memory

		self.gamma = GAMMA
		self.lr = LR
		self.tau = TAU
		self.batch_size = BATCH_SIZE

		self.optimizer = optim.Adam(self.NN.parameters(), self.lr)

		self.noise = OrnsteinUhlenbeckNoise(self.NN.action_dim)

		hard_update(self.target_NN,self.NN )

		self.algo = algo

	
	def act(self, x,exploitation=False) :
		#state = Variable( torch.from_numpy(x), volatile=True )
		state = Variable( x, volatile=True )
		if self.use_cuda :
			state = state.cuda()
		action = self.NN.actor( state).detach()
		
		if exploitation :
			return action.cpu().data.numpy()
		else :
			# exploration :
			new_action = action.cpu().data.numpy() + self.noise.sample()*self.NN.action_scaler
			return new_action

	def evaluate(self, x,a) :
		state = Variable( x, volatile=True )
		action = Variable( a, volatile=True )
		if self.use_cuda :
			state = state.cuda()
			action = action.cuda()

		qsa = self.NN.critic( state, action).detach()
		
		return qsa.cpu().data.numpy()

	def optimize(self,MIN_MEMORY=1e3) :

		if self.algo == 'ddpg' :
			try :
				if len(self.memory) < MIN_MEMORY :
					return
				
				#Create Batch with PR :
				prioritysum = self.memory.total()
				randexp = np.random.random(size=self.batch_size)*prioritysum
				batch = list()
				for i in range(self.batch_size):
					try :
						el = self.memory.get(randexp[i])
						batch.append(el)
					except TypeError as e :
						continue
						#print('REPLAY BUFFER EXCEPTION...')
				
				# Create Batch with replayMemory :
				batch = TransitionPR( *zip(*batch) )
				next_state_batch = Variable(torch.cat( batch.next_state), requires_grad=False)
				state_batch = Variable( torch.cat( batch.state) , requires_grad=False)
				action_batch = Variable( torch.cat( batch.action) , requires_grad=False)
				reward_batch = Variable( torch.cat( batch.reward ), requires_grad=False ).view((-1,1))
				
				if self.use_cuda :
					next_state_batch = next_state_batch.cuda()
					state_batch = state_batch.cuda()
					action_batch = action_batch.cuda()
					reward_batch = reward_batch.cuda()

				#before optimization :
				self.optimizer.zero_grad()
			
				# Critic :
				# sample action from next_state, without gradient repercusion :
				next_taction = self.target_NN.actor(next_state_batch).detach()
				# evaluate the next state action over the target, without repercusion (faster...) :
				next_tqsa = torch.squeeze( self.target_NN.critic( next_state_batch, next_taction).detach() )
				# Supervise loss :
				## y_true :
				y_true = reward_batch + self.gamma*next_tqsa 
				## y_pred :
				y_pred = torch.squeeze( self.NN.critic(state_batch,action_batch) )
				## loss :
				critic_loss = F.smooth_l1_loss(y_pred,y_true)
				#critic_loss.backward()
				#self.optimizer.step()

				# Actor :
				pred_action = self.NN.actor(state_batch)
				pred_qsa = torch.squeeze( self.target_NN.critic(state_batch, pred_action) )
				# loss :
				actor_loss = -1.0*torch.sum( pred_qsa)
				#actor_loss.backward()
				#self.optimizer.step()

				# optimize both pathway :
				scalerA = 0.1
				scalerV = 10.0
				total_loss = scalerA*actor_loss + scalerV*critic_loss
				total_loss.backward()
				self.optimizer.step()

			except Exception as e :
				bashlogger.debug('error : {}',format(e) )
				

			# soft update :
			soft_update(self.target_NN, self.NN, self.tau)

			return critic_loss.cpu().data.numpy(), actor_loss.cpu().data.numpy()

		else :
			raise NotImplemented


	def optimizeSEPARATED(self,MIN_MEMORY=1e3) :

		if self.algo == 'ddpg' :
			try :
				if len(self.memory) < MIN_MEMORY :
					return
				
				#Create Batch with PR :
				prioritysum = self.memory.total()
				randexp = np.random.random(size=self.batch_size)*prioritysum
				batch = list()
				for i in range(self.batch_size):
					try :
						el = self.memory.get(randexp[i])
						batch.append(el)
					except TypeError as e :
						continue
						#print('REPLAY BUFFER EXCEPTION...')
				
				# Create Batch with replayMemory :
				batch = TransitionPR( *zip(*batch) )
				next_state_batch = Variable(torch.cat( batch.next_state), requires_grad=False)
				state_batch = Variable( torch.cat( batch.state) , requires_grad=False)
				action_batch = Variable( torch.cat( batch.action) , requires_grad=False)
				reward_batch = Variable( torch.cat( batch.reward ), requires_grad=False ).view((-1,1))
				'''
				next_state_batch = Variable(torch.cat( batch.next_state) )
				state_batch = Variable( torch.cat( batch.state) )
				action_batch = Variable( torch.cat( batch.action) )
				reward_batch = Variable( torch.cat( batch.reward ) ).view((-1,1))
				'''
				
				if self.use_cuda :
					next_state_batch = next_state_batch.cuda()
					state_batch = state_batch.cuda()
					action_batch = action_batch.cuda()
					reward_batch = reward_batch.cuda()

				
				# Critic :
				# sample action from next_state, without gradient repercusion :
				next_taction = self.target_NN.actor(next_state_batch).detach()
				# evaluate the next state action over the target, without repercusion (faster...) :
				next_tqsa = torch.squeeze( self.target_NN.critic( next_state_batch, next_taction).detach() )
				# Supervise loss :
				## y_true :
				y_true = reward_batch + self.gamma*next_tqsa 
				## y_pred :
				y_pred = torch.squeeze( self.NN.critic(state_batch,action_batch) )
				## loss :
				critic_loss = F.smooth_l1_loss(y_true,y_pred)
				#before optimization :
				self.optimizer.zero_grad()
				critic_loss.backward()
				self.optimizer.step()

				
				
				# Actor :
				pred_action = self.NN.actor(state_batch)
				pred_qsa = torch.squeeze( self.NN.critic(state_batch, pred_action) )
				# loss :
				actor_loss = -1.0*torch.sum( pred_qsa)
				#before optimization :
				self.optimizer.zero_grad()
				actor_loss.backward()
				self.optimizer.step()
				
			except Exception as e :
				bashlogger.debug('error : {}',format(e) )


			# soft update :
			soft_update(self.target_NN, self.NN, self.tau)

			return critic_loss.cpu().data.numpy(), actor_loss.cpu().data.numpy()

		else :
			raise NotImplemented

	def save(self,path) :
		torch.save( self.NN.state_dict(), path)

	def load(self, path) :
		self.NN.load_state_dict( torch.load(path) )
		hard_update(self.target_NN, self.NN)



class Model2 :
	def __init__(self, actor, critic, memory, algo='ddpg',GAMMA=GAMMA,LR=LR,TAU=TAU,use_cuda=USE_CUDA,BATCH_SIZE=BATCH_SIZE ) :
		self.actor = actor
		self.critic = critic
		self.target_actor = copy.deepcopy(actor)
		self.target_critic = copy.deepcopy(critic)

		self.use_cuda = use_cuda
		if self.use_cuda :
			self.actor = self.actor.cuda()
			self.target_actor = self.target_actor.cuda()
			self.critic = self.critic.cuda()
			self.target_critic = self.target_critic.cuda()


		self.memory = memory

		self.gamma = GAMMA
		self.lr = LR
		self.tau = TAU
		self.batch_size = BATCH_SIZE

		self.optimizer_actor = optim.Adam(self.actor.parameters(), self.lr)
		self.optimizer_critic = optim.Adam(self.critic.parameters(), self.lr*1e2)

		self.noise = OrnsteinUhlenbeckNoise(self.actor.action_dim)

		hard_update(self.target_actor, self.actor)
		hard_update(self.target_critic, self.critic)

		self.algo = algo

	
	def act(self, x,exploitation=False) :
		#self.actor.eval()
		
		#state = Variable( torch.from_numpy(x), volatile=True )
		state = Variable( x, volatile=True )
		if self.use_cuda :
			state = state.cuda()
		action = self.actor( state).detach()
		
		if exploitation :
			return action.cpu().data.numpy()
		else :
			# exploration :
			new_action = action.cpu().data.numpy() + self.noise.sample()*self.actor.action_scaler
			return new_action

	def evaluate(self, x,a) :
		#self.critic.eval()
		
		state = Variable( x, volatile=True )
		action = Variable( a, volatile=True )
		if self.use_cuda :
			state = state.cuda()
			action = action.cuda()

		qsa = self.critic( state, action).detach()
		
		return qsa.cpu().data.numpy()

	def optimize(self,MIN_MEMORY=1e3) :
		'''
		self.target_critic.eval()
		self.target_actor.eval()
		self.critic.train()
		self.actor.train()
		'''

		if self.algo == 'ddpg' :
			try :
				if len(self.memory) < MIN_MEMORY :
					return
				
				#Create Batch with PR :
				prioritysum = self.memory.total()
				randexp = np.random.random(size=self.batch_size)*prioritysum
				batch = list()
				for i in range(self.batch_size):
					try :
						el = self.memory.get(randexp[i])
						batch.append(el)
					except TypeError as e :
						continue
						#print('REPLAY BUFFER EXCEPTION...')
				
				# Create Batch with replayMemory :
				batch = TransitionPR( *zip(*batch) )
				next_state_batch = Variable(torch.cat( batch.next_state), requires_grad=False)
				state_batch = Variable( torch.cat( batch.state) , requires_grad=False)
				action_batch = Variable( torch.cat( batch.action) , requires_grad=False)
				reward_batch = Variable( torch.cat( batch.reward ), requires_grad=False ).view((-1))
				'''
				next_state_batch = Variable(torch.cat( batch.next_state) )
				state_batch = Variable( torch.cat( batch.state) )
				action_batch = Variable( torch.cat( batch.action) )
				reward_batch = Variable( torch.cat( batch.reward ) ).view((-1,1))
				'''
				
				if self.use_cuda :
					next_state_batch = next_state_batch.cuda()
					state_batch = state_batch.cuda()
					action_batch = action_batch.cuda()
					reward_batch = reward_batch.cuda()

				
				# Critic :
				# sample action from next_state, without gradient repercusion :
				next_taction = self.target_actor(next_state_batch).detach()
				# evaluate the next state action over the target, without repercusion (faster...) :
				next_tqsa = torch.squeeze( self.target_critic( next_state_batch, next_taction).detach() ).view((-1))
				# Supervise loss :
				## y_true :
				y_true = reward_batch + self.gamma*next_tqsa 
				## y_pred :
				y_pred = torch.squeeze( self.critic(state_batch,action_batch) )
				## loss :
				critic_loss = F.smooth_l1_loss(y_pred,y_true)
				#before optimization :
				self.optimizer_critic.zero_grad()
				critic_loss.backward()
				self.optimizer_critic.step()
				
				'''
				critic_grad = 0.0
				for p in self.critic.parameters() :
					critic_grad += np.mean(p.grad.cpu().data.numpy())
				print( 'Mean Critic Grad : {}'.format(critic_grad) )
				'''

				# Actor :
				pred_action = self.actor(state_batch)
				pred_qsa = torch.squeeze( self.critic(state_batch, pred_action) )
				# loss :
				actor_loss = -1.0*torch.mean( pred_qsa)
				#before optimization :
				self.optimizer_actor.zero_grad()
				actor_loss.backward()
				self.optimizer_actor.step()

				
				actor_grad = 0.0
				for p in self.actor.parameters() :
					actor_grad += np.mean( np.abs(p.grad.cpu().data.numpy() ) )
				#print( 'Mean Actor Grad : {}'.format(actor_grad) )
				

			except Exception as e :
				bashlogger.debug('error : {}',format(e) )
				

			# soft update :
			soft_update(self.target_critic, self.critic, self.tau)
			soft_update(self.target_actor, self.actor, self.tau)

			del batch
			del next_state_batch 
			del state_batch 
			del action_batch 
			del reward_batch 

			closs = critic_loss.cpu()
			aloss = actor_loss.cpu()
			del actor_loss
			del critic_loss

			return closs.data.numpy(), aloss.data.numpy(), actor_grad

		else :
			raise NotImplemented


	def save(self,path) :
		torch.save( self.actor.state_dict(), path+'.actor')
		torch.save( self.critic.state_dict(), path+'.critic')

	def load(self, path) :
		self.actor.load_state_dict( torch.load(path+'.actor') )
		hard_update(self.target_actor, self.actor)
		self.critic.load_state_dict( torch.load(path+'.critic') )
		hard_update(self.target_critic, self.critic)