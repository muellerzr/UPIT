# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/03_train.cyclegan.ipynb (unless otherwise specified).

__all__ = ['CycleGANLoss', 'CycleGANTrainer', 'AvgMetric', 'combined_flat_anneal', 'cycle_learner']

# Cell
from fastai.vision.all import *
from fastai.basics import *
from typing import List
from fastai.vision.gan import *
from ..models.cyclegan import *
from ..data.unpaired import *

# Cell
class CycleGANLoss(nn.Module):
    """
    CycleGAN loss function. The individual loss terms are also atrributes of this class that are accessed by fastai for recording during training.

    Attributes:

    `self.cgan` (`nn.Module`): The CycleGAN model.

    `self.l_A` (`float`): lambda_A, weight of domain A losses.

    `self.l_B` (`float`): lambda_B, weight of domain B losses.

    `self.l_idt` (`float`): lambda_idt, weight of identity lossees.

    `self.crit` (`AdaptiveLoss`): The adversarial loss function (either a BCE or MSE loss depending on `lsgan` argument)

    `self.real_A` and `self.real_B` (`fastai.torch_core.TensorImage`): Real images from domain A and B.

    `self.id_loss_A` (`torch.FloatTensor`): The identity loss for domain A calculated in the forward function

    `self.id_loss_B` (`torch.FloatTensor`): The identity loss for domain B calculated in the forward function

    `self.gen_loss` (`torch.FloatTensor`): The generator loss calculated in the forward function

    `self.cyc_loss` (`torch.FloatTensor`): The cyclic loss calculated in the forward function
    """


    def _create_gan_loss(self, loss_func):
        """
        Create adversarial loss function. It takes in an existing loss function (like those from torch.nn.functional), and returns a
        loss function that allows comparison between discriminator output feature map, and single values (0 or 1 for real and fake)
        """
        def gan_loss_func(output, target):
            return loss_func(output, torch.Tensor([target]).expand_as(output).to(output.device))
        return gan_loss_func


    def __init__(self, cgan:nn.Module, l_A:float=10., l_B:float=10, l_idt:float=0.5, lsgan:bool=True):
        """
        Constructor for CycleGAN loss.

        Arguments:

        `cgan` (`nn.Module`): The CycleGAN model.

        `l_A` (`float`): weight of domain A losses. (default=10)

        `l_B` (`float`): weight of domain B losses. (default=10)

        `l_idt` (`float`): weight of identity losses. (default=0.5)

        `lsgan` (`bool`): Whether or not to use LSGAN objective. (default=True)
        """
        super().__init__()
        store_attr(self,'cgan,l_A,l_B,l_idt,lsgan')
        self.crit = self._create_gan_loss(F.mse_loss if self.lsgan else F.binary_cross_entropy)

    def set_input(self, input): self.real_A,self.real_B = input

    def forward(self, output, target, discriminator=False):
        """
        Forward function of the CycleGAN loss function. The generated images are passed in as output (which comes from the model)
        and the generator loss is returned. If `discriminator` is set to True, the discriminator adversarial loss will be calculated
        and returned instead.
        """
        if discriminator: #if discriminator argument is True, calculate and return the adversarial discriminator
            fake_A, fake_B = output
            real_A, real_B = target
            self.D_A_loss = 0.5 * (self.crit(self.cgan.D_A(real_A), 1) + self.crit(self.cgan.D_A(fake_A), 0))
            self.D_B_loss = 0.5 * (self.crit(self.cgan.D_B(real_B), 1) + self.crit(self.cgan.D_B(fake_B), 0))
            return self.D_A_loss, self.D_B_loss

        fake_A, fake_B, idt_A, idt_B = output
        #Generators should return identity on the datasets they try to convert to
        self.id_loss_A = self.l_idt * self.l_A * F.l1_loss(idt_A, self.real_A)
        self.id_loss_B = self.l_idt * self.l_B * F.l1_loss(idt_B, self.real_B)
        #Generators are trained to trick the discriminators so the following should be ones
        self.gen_loss_A = self.crit(self.cgan.D_A(fake_A), 1)
        self.gen_loss_B = self.crit(self.cgan.D_B(fake_B), 1)
        #Cycle loss
        self.cyc_loss_A = self.l_A * F.l1_loss(self.cgan.G_A(fake_B), self.real_A)
        self.cyc_loss_B = self.l_B * F.l1_loss(self.cgan.G_B(fake_A), self.real_B)
        return self.id_loss_A+self.id_loss_B+self.gen_loss_A+self.gen_loss_B+self.cyc_loss_A+self.cyc_loss_B

# Cell
class CycleGANTrainer(Callback):
    run_before = Recorder

    def _set_trainable(self, disc=False):
        """Put the generators or discriminators in training mode depending on arguments."""
        def set_requires_grad(m, rg):
            for p in m.parameters(): p.requires_grad_(rg)
        set_requires_grad(self.learn.model.G_A, not disc)
        set_requires_grad(self.learn.model.G_B, not disc)
        set_requires_grad(self.learn.model.D_A, disc)
        set_requires_grad(self.learn.model.D_B, disc)
        if disc: self.opt_D.hypers = self.learn.opt.hypers

    def before_train(self, **kwargs):
        self.G_A,self.G_B = self.learn.model.G_A,self.learn.model.G_B
        self.D_A,self.D_B = self.learn.model.D_A,self.learn.model.D_B
        self.crit = self.learn.loss_func.crit
        if not getattr(self,'opt_G',None):
            self.opt_G = self.learn.opt_func(self.learn.splitter(nn.Sequential(*flatten_model(self.G_A), *flatten_model(self.G_B))), self.learn.lr)
        else:
            self.opt_G.hypers = self.learn.opt.hypers
        if not getattr(self, 'opt_D',None):
            self.opt_D = self.learn.opt_func(self.learn.splitter(nn.Sequential(*flatten_model(self.D_A), *flatten_model(self.D_B))), self.learn.lr)
        else:
            self.opt_D.hypers = self.learn.opt.hypers

        self.learn.opt = self.opt_G
        self._set_trainable()

    def before_batch(self, **kwargs):
        self._training = self.learn.model.training
        self.learn.xb = (self.learn.xb[0],self.learn.yb[0]),
        self.learn.loss_func.set_input(*self.learn.xb)

    def after_step(self):
        self.opt_D.hypers = self.learn.opt.hypers

    def after_batch(self, **kwargs):
        self.G_A.zero_grad(); self.G_B.zero_grad()
        if self._training:
            self._set_trainable(disc=True)
            self.D_A.zero_grad(); self.D_B.zero_grad()
            loss_D_A, loss_D_B = self.learn.loss_func(self.learn.xb[0], (self.learn.pred[0].detach(), self.learn.pred[1].detach()), discriminator=True)
            loss_D_A.backward()
            loss_D_B.backward()
            self.opt_D.step()
            self._set_trainable()

    def before_validate(self, **kwargs):
        self.G_A,self.G_B = self.learn.model.G_A,self.learn.model.G_B
        self.D_A,self.D_B = self.learn.model.D_A,self.learn.model.D_B
        self.crit = self.learn.loss_func.crit

# Cell
class AvgMetric(Metric):
    """
    Average the values of `func` taking into account potential different batch sizes.
    Overwrites fastai's version by including argument to decode the output image
    """
    def __init__(self, func, decode=True):
        self.func = func
        self.decode = denorm
    def reset(self): self.total,self.count = 0.,0
    def accumulate(self, learn):
        bs = find_bs(learn.yb)
        args = [*learn.xb[0], *learn.pred, *learn.yb]
        if self.decode: args = [learn.dls.after_batch.decode(TensorImage(b)).float() for b in args]
        self.total += to_detach(self.func(*args))*bs
        self.count += bs
    @property
    def value(self): return self.total/self.count if self.count != 0 else None
    @property
    def name(self):  return self.func.func.__name__ if hasattr(self.func, 'func') else  self.func.__name__

# Cell
def combined_flat_anneal(pct:float, start_lr:float, end_lr:float=0, curve_type:str='linear'):
    """
    Create a schedule with constant learning rate `start_lr` for `pct` proportion of the training, and a `curve_type` learning rate (till `end_lr`) for remaining portion of training.

    Arguments:
    `pct` (`float`): Proportion of training with a constant learning rate.

    `start_lr` (`float`): Desired starting learning rate, used for beginnning `pct` of training.

    `end_lr` (`float`): Desired end learning rate, training will conclude at this learning rate.

    `curve_type` (`str`): Curve type for learning rate annealing. Options are 'linear', 'cosine', and 'exponential'.
    """
    if curve_type == 'linear':      SchedAnneal = SchedLin
    if curve_type == 'cosine':      SchedAnneal = SchedCos
    if curve_type == 'exponential': SchedAnneal = SchedExp
    schedule = combine_scheds([pct,1-pct],[SchedNo(start_lr,start_lr),SchedAnneal(start_lr,end_lr)])
    return schedule

# Cell
@patch
def fit_flat_lin(self:Learner, n_epochs:int=100, n_epochs_decay:int=100, start_lr:float=None, end_lr:float=0, curve_type:str='linear', wd:float=None,
                 cbs=None, reset_opt=False):
    "Fit `self.model` for `n_epoch` at flat `start_lr` before `curve_type` annealing to `end_lr` with weight decay of `wd` and callbacks `cbs`."
    total_epochs = n_epochs+n_epochs_decay
    pct_start = n_epochs/total_epochs
    if self.opt is None: self.create_opt()
    self.opt.set_hyper('lr', self.lr if start_lr is None else start_lr)
    start_lr = np.array([h['lr'] for h in self.opt.hypers])
    scheds = {'lr': combined_flat_anneal(pct_start, start_lr, end_lr, curve_type)}
    self.fit(total_epochs, cbs=ParamScheduler(scheds)+L(cbs), reset_opt=reset_opt, wd=wd)

# Cell
@delegates(Learner.__init__)
def cycle_learner(dls, m, opt_func=Adam, metrics=[], cbs=[], **kwargs):
    lms = LossMetrics(['id_loss_A', 'id_loss_B','gen_loss_A','gen_loss_B','cyc_loss_A','cyc_loss_B',
                       'D_A_loss', 'D_B_loss'])

    learn = Learner(dls, m, loss_func=CycleGANLoss(m), opt_func=opt_func,
                    cbs=[CycleGANTrainer, *cbs],metrics=[*lms, *[AvgMetric(metric) for metric in [*metrics]]])

    learn.recorder.train_metrics = True
    learn.recorder.valid_metrics = False
    return learn