# -*- coding: utf-8 -*-
"""
Created on Fri Jan 25 14:26:14 2019

@author: roger luo

class
-----

ML_model:
    quantifying predictions of an estimator and perform parameter tuning
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os
import copy

from scipy import interp
from sklearn.utils import validation, check_consistent_length
from sklearn.base import BaseEstimator
from sklearn.model_selection import _split
from sklearn.model_selection import (GridSearchCV, RandomizedSearchCV,
                                     cross_val_score, cross_validate)
from sklearn.model_selection import _validation
from sklearn.metrics import roc_curve, auc
from functools import wraps
from shutil import rmtree

from lw_mlearn.utilis.utilis import get_flat_list, get_kwargs
from lw_mlearn.utilis.plotter import (plotter_auc, plotter_cv_results_, 
                                      plotter_score_path)
from lw_mlearn.utilis.read_write import Objs_management
from lw_mlearn.lw_preprocess import (pipe_main, pipe_grid, _binning, 
                            selected_fearturename,
                            plotter_lift_curve, 
                            get_custom_scorer)
from lw_mlearn.utilis.docstring import Appender, dedent

class ML_model(BaseEstimator):
    '''quantifying predictions of an estimator
    
    parameters
    ---
    estimator
        - sklearn estimator or pipeline instance
    path
        - dir to place model and other files, default 'model'
    seed
        - random state seed, 0 default
    pos_label
            - positive label default 1
       
    attributes
    ----------
    path
        - directory to read/dump object from 
    gridcv_results
        - cv_results after running grid_searchcv
    folder
        - read_write object to load/dump datafiles from self.path
    bins
        - bin edges of predictions of estimator
    
    testscore
        - averaged score for test set returned by run_anlysis
    trainscore
        - averaged score for train set returned by run_anlysis
    
    method
    ---------
    cv_score:
        return cross score of estimator
    cv_validate:
        return cross score of estimator, allowing multi scorers
    grid_searchcv:
        perform grid search of param_grid, update self esimator estimator
    rand_searchcv:
        perform randomized search of param_grid, update self estimator
    fit:
        perform fit of estimator
    predict:
        perform predict of estimator 
        
    plot_auc_test:
        plot auc of test data
    plot_auc_traincv:
        plot auc of train data
    plot_lift:
        plot lift curve of model
    plot_gridcv:
        plot  grid seach cv results of model
    '''
    @staticmethod
    def from_config(config):
        ''' return ML_model instance from saved configuration parameters
        '''
        return ML_model(**config)

    def __init__(self,
                 estimator=None,
                 path='model',
                 seed=0,
                 verbose=1,
                 pos_label=1):
        ''' if estimator is None, try to read an '.pipe' estimator from path, 
        and if there's no such '.pipe', use a dummy classifier instead
        '''
        self.path = path
        self.verbose = verbose
        self.pos_label = pos_label
        self.seed = seed
        self.gridcv_results = None

        if estimator is not None:
            if isinstance(estimator, str):
                self.estimator = pipe_main(estimator)
            elif hasattr(estimator, '_estimator_type'):
                self.estimator = estimator
            else:
                raise ValueError('invalid estimator input type: {}'.format(
                    estimator.__class__.__name__))
        else:
            gen, _ = self.folder.read_all(suffix='.pipe')
            if len(gen) > 0:
                self.estimator = gen[0]
                print('estimator {} has been read from {}'.format(
                    self.estimator.__class__.__name__, self.folder.path_))
            else:
                self.estimator = pipe_main('dummy')
                print('no estimator input, use a dummy classifier ... \n')

    def _shut_temp_folder(self):
        '''shut temp folder directory
        '''
        if getattr(self.estimator, 'memory') is not None:
            while os.path.exists(self.estimator.memory):
                rmtree(self.estimator.memory, ignore_errors=True)

            print('%s has been removed' % self.estimator.memory)
            self.estimator.memory = None

    def _check_fitted(self, estimator):
        '''check if estimator has been fitted
        '''
        validation.check_is_fitted(
            estimator,
            ['classes_', 'coef_', 'feature_importances_', 'booster', 'tree_'],
            all_or_any=any)

    def _pre_continueous(self, estimator, X):
        '''make continueous predictions
        '''
        classes_ = getattr(estimator, 'classes_')
        if len(classes_) > 2:
            raise ValueError(' estimator should only output binary classes...')

        if hasattr(estimator, 'decision_function'):
            method = getattr(estimator, 'decision_function')
            y_pre = method(X)
        elif hasattr(estimator, 'predict_proba'):
            method = getattr(estimator, 'predict_proba')
            y_pre = method(X)
        else:
            raise ValueError('estimator have no continuous predictions')

        if np.ndim(y_pre) > 1:
            y_pre = y_pre[:, self.pos_label]
        return y_pre

    def _get_dataset(self, suffix):
        '''return list of obj read from 'data' folder given suffix type
        '''
        gen, _ = self.folder.read_all(suffix, path='data')
        if len(gen) == 0:
            raise FileNotFoundError(
                "file with '{}' suffix not found in 'data' folder... \n".
                format(suffix))
        return gen

    def _get_scorer(self, scoring):
        ''' return sklearn scorer, including custom scorer
        '''
        scorer = {}
        sk_scoring = []
        custom_scorer = get_custom_scorer()
        for i in get_flat_list(scoring):
            if i in custom_scorer:
                scorer.update({i: custom_scorer[i]})
            else:
                sk_scoring.append(i)
        if len(sk_scoring) > 0:
            s, _ = _validation._check_multimetric_scoring(self.estimator,
                                                          scoring=sk_scoring)
            scorer.update(s)
        return scorer

    @property
    def folder(self):
        return Objs_management(self.path)

    def plot_auc_test(self,
                      X,
                      y,
                      cv=1,
                      groups=None,
                      title=None,
                      ax=None,
                      save_fig=False):
        '''plot roc_auc curve for given fitted estimator, must have continuous
        predictons (decision_function or predict_proba) to evaluate model by
        roc_auc metrics(iterables of X, y can be passed or X, y 
        can be splited using cv > 1), to assess model fit performance

        X
            -2D array or list of 2D ndarrays
        y
            -binary or list of class labels
        cv 
            -int, cross-validation generator or an iterable
            - if cv>1, generate splits by StratifyKfold method
        title
            - title added to plot header as to indicate (X, y)
        return
        --------
        ax, mean-auc, std-auc,
       
        data_splits:
           list of test data set in the form of DataFrame (combined X & y)
        '''
        L = locals().copy()
        L.pop('self')
        estimator = self.estimator
        # split test set by cv
        if cv > 1:
            xs = []
            ys = []
            data_splits = tuple(
                _split_cv(X, y=y, cv=cv, groups=groups,
                          random_state=self.seed))
            for x_set, y_set in data_splits:
                xs.append(x_set[1])
                ys.append(y_set[1])
            L.update({'X': xs, 'y': ys, 'cv': 1})
            return self.plot_auc_test(**L)

        self._check_fitted(estimator)
        X = get_flat_list(X)
        y = get_flat_list(y)
        validation.check_consistent_length(X, y)
        fprs = []
        tprs = []
        aucs = []
        n_sample = 0
        for i in range(len(X)):
            x0 = X[i]
            y0 = y[i]
            y_pre = self._pre_continueous(estimator, x0)
            fpr, tpr, threshhold = roc_curve(y0, y_pre, drop_intermediate=True)
            fprs.append(fpr)
            tprs.append(tpr)
            aucs.append(auc(fpr, tpr))
            n_sample += len(x0)
        # -- plot
        if ax is None:
            fig, ax = plt.subplots(1, 1)
        ax = plotter_auc(fprs, tprs, ax=ax)

        header = '-'.join([
            _get_estimator_name(estimator), 'testCV',
            '{} samples'.format(n_sample)
        ])
        if isinstance(title, str):
            header = '-'.join([title, header])
        ax.set_title(header)

        data_splits = [
            pd.concat((pd.DataFrame(i) for i in item), axis=1)
            for item in zip(X, y)
        ]

        if save_fig is True:
            if isinstance(title, str):
                plot_name = 'plots/roc_test_' + title + '.pdf'
            else:
                plot_name = 'plots/roc_test.pdf'
            self.folder.write(plt.gcf(), plot_name)
            plt.close()
        return ax, np.mean(aucs), np.std(aucs), data_splits

    def plot_auc_traincv(self,
                         X,
                         y,
                         cv=5,
                         groups=None,
                         title=None,
                         ax=None,
                         save_fig=False,
                         **fit_params):
        '''fit & plot roc_auc of an estimator, must have continuous
        predictons (to assess hyper parameter settings performance)

        X
            -2D array  or DataFrame
        y
            -binary class labels  , 1D array             
        cv 
            -int, cross-validation generator or an iterable
            - if cv>1, generate splits by StratifyKfold method
        title
            - title added to plot header
        fit_params
            -other fit parameters
        return
        ----
        ax, mean_auc, std_auc,
        
        data_splits:
            list of test data set in the form of DataFrame
        '''

        estimator = self.estimator

        clf = copy.deepcopy(estimator)
        tprs = []
        aucs = []
        fpr_ = []
        tpr_ = []
        mean_fpr = np.linspace(0, 1, 100)
        data_splits = list(
            _split_cv(X, y=y, cv=cv, groups=groups, random_state=self.seed))

        for x_set, y_set in data_splits:
            xx = x_set[0]
            yy = y_set[0]
            clf.fit(xx, yy, **fit_params)
            y_pre = self._pre_continueous(clf, x_set[1])
            fpr, tpr, threshhold = roc_curve(y_set[1],
                                             y_pre,
                                             drop_intermediate=True)
            tprs.append(interp(mean_fpr, fpr, tpr))
            fpr_.append(fpr)
            tpr_.append(tpr)
            tprs[-1][0] = 0.0
            roc_auc = auc(fpr, tpr)
            aucs.append(roc_auc)

        mean_auc = np.mean(aucs)
        std_auc = np.std(aucs)
        # -- plot
        if ax is None:
            fig, ax = plt.subplots(1, 1)

        ax = plotter_auc(fpr_, tpr_, ax=ax)

        header = '-'.join(
            [_get_estimator_name(clf), 'trainCV', '{} samples'.format(len(y))])
        if isinstance(title, str):
            header = '-'.join([title, header])
        ax.set_title(header)
        if save_fig is True:
            if isinstance(title, str):
                plot_name = 'plots/roc_train_' + title + '.pdf'
            else:
                plot_name = 'plots/roc_train.pdf'
            self.folder.write(plt.gcf(), plot_name)
            plt.close()
        return ax, mean_auc, std_auc, _get_splits_combined(data_splits)

    def plot_lift(self,
                  X,
                  y,
                  q=None,
                  bins=None,
                  max_leaf_nodes=None,
                  use_self_bins=False,
                  labels=False,
                  ax=None,
                  title=None,
                  save_fig=False,
                  **tree_kwargs):
        '''plot list curve of (X, y) data, update self bins
        
            given bins(n equal width) or q( n equal frequency) or 
            max_leaf_nodes cut by tree
        X
            -2D array
        y
            -binary class labels , 1D array

        q
            - number of equal frequency
        bins
            - number of equal width or array of edges
        max_leaf_nodes
            - if not None perform supervised cutting, 
            - number of tree nodes using tree cut
        use_self_bins
            - use self.estimator.bins if true

        .. note::
            -  only 1 of (q, bins, max_leaf_nodes) can be specified

        **tree_kwargs - Decision tree keyswords, egg:
            - min_impurity_decrease=0.001
            - random_state=0
        labels
            - see pd.cut, if False return integer indicator of bins, 
            - if True/None return arrays of labels (or can be passed )       
        title
            - title XXX of plot, output format: 'XXX' + estimator's name
        return
        ----
        ax,  plotted_data;
        '''

        self._check_fitted(self.estimator)
        estimator = self.estimator
        y_pre = self._pre_continueous(estimator, X)

        if use_self_bins is True:
            if hasattr(self.estimator, 'bins'):
                bins = self.estimator.bins
                q = None
                max_leaf_nodes = None
            else:
                print("'self.estimator.bins' is None, no lift curve plot \n")
                return
            
        header = _get_estimator_name(estimator) + ' - lift curve'
        if not (title is None):
            header = ' - '.join([title, header])

        if ax is None:
            fig, ax = plt.subplots(1, 1)
        ax, y_cut, bins, plotted_data = plotter_lift_curve(
            y_pre,
            y_true=y,
            bins=bins,
            q=q,
            header=header,
            max_leaf_nodes=max_leaf_nodes,
            labels=labels,
            ax=ax,
            **tree_kwargs)
        # update self bins
        self.estimator.bins = bins

        if save_fig is True:
            title = 0 if title is None else str(title)
            self.folder.write(plt.gcf(), 'plots/lift{}.pdf'.format(title))
            plt.close()
        return ax, plotted_data

    def plot_gridcv(self, title=None, save_fig=False):
        '''plot grid seatch cv results
        '''
        header = '-'.join([_get_estimator_name(self.estimator), 'gridcv'])
        if title is None:
            pass
        else:
            header = '-'.join([title, header])
        if self.gridcv_results is None:
            print('no grid cv results')
        else:
            plotter_cv_results_(self.gridcv_results, title=header)

        if save_fig is True:
            if isinstance(title, str):
                plot_name = 'plots/gridcv_' + title + '.pdf'
            else:
                plot_name = 'plots/gridcv.pdf'
            self.folder.write(plt.gcf(), plot_name)
            plt.close()

    @wraps(cross_val_score)
    def cv_score(self, X, y, scoring='roc_auc', cv=5, **kwargs):
        '''
        return cross validated score of estimator (see cross_val_score)
        ---------
        '''
        scorer = self._get_scorer(scoring)
        return cross_val_score(self.estimator,
                               X=X,
                               y=y,
                               scoring=scorer,
                               cv=cv,
                               **get_kwargs(cross_val_score, **kwargs))

    @wraps(cross_validate)
    def cv_validate(self,
                    X,
                    y,
                    scoring='roc_auc',
                    cv=5,
                    return_estimator=False,
                    return_train_score=False,
                    **kwargs):
        '''       
        return cross_validate results of estimator(see cross_validate)
        -----
        cv_results: 
            (as DataFrame, allowing for multi-metrics) in the form of
            'test_xxx', train_xxx' where  'xxx' is scorer name
        '''
        estimator = self.estimator
        L = locals().copy()
        L.pop('self')
        L.pop('scoring')
        scorer = self._get_scorer(scoring)
        # --
        cv_results = cross_validate(scoring=scorer,
                                    **get_kwargs(cross_validate, **L,
                                                 **kwargs))
        return pd.DataFrame(cv_results)

    def test_score(self, X, y, cv, scoring):
        '''return test scores of estimator 
        '''
        # test scores
        data_splits = _split_cv(X, y=y, cv=cv, random_state=self.seed)
        # get_scorers = _validation._check_multimetric_scoring
        # scorer, _ = get_scorers(self.estimator, scoring=scoring)
        # is_multimetric = not callable(scorer)
        scorer = self._get_scorer(scoring)
        is_multimetric = not callable(scorer)
        scores = []
        for item in data_splits:
            x0 = item[0][1]
            y0 = item[1][1]
            scores.append(
                _validation._score(self.estimator, x0, y0, scorer,
                                   is_multimetric))
        scores = pd.DataFrame(scores).reset_index(drop=True)
        return scores

    @wraps(GridSearchCV)
    def grid_searchcv(self,
                      X,
                      y,
                      param_grid,
                      scoring='roc_auc',
                      cv=3,
                      refit='roc_auc',
                      return_train_score=True,
                      n_jobs=2,
                      fit_params={},
                      **kwargs):
        '''tune hyper parameters of estimator by searching param_grid
        , update self.estimator & self.gridcv_results
        
        return
        -----
        cv_results as DataFrame
        '''
        L = locals().copy()
        L.pop('self')
        L.pop('fit_params')
        L.pop('scoring')
        scorer = self._get_scorer(scoring)
        # --
        estimator = self.estimator
        grid = GridSearchCV(estimator,
                            scoring=scorer,
                            **get_kwargs(GridSearchCV, **L),
                            **kwargs)

        grid.fit(X, y, **fit_params)
        cv_results = pd.DataFrame(grid.cv_results_)
        self.estimator = grid.best_estimator_
        self.gridcv_results = cv_results
        return cv_results

    @wraps(RandomizedSearchCV)
    def rand_searchcv(self,
                      X,
                      y,
                      param_distributions,
                      scoring='roc_auc',
                      cv=3,
                      refit=None,
                      return_train_score=True,
                      fit_params={},
                      njobs=2,
                      **kwargs):
        '''tune hyper parameters of estimaotr by randomly searching param_grid
        , update self estimator & grid search results     
        return
        -----
        cv_results as DataFrame
        '''
        L = locals().copy()
        L.pop('self')
        # --
        estimator = self.estimator
        grid = RandomizedSearchCV(estimator,
                                  **get_kwargs(RandomizedSearchCV, **L),
                                  **kwargs)
        grid.fit(X, y, **fit_params)
        cv_results = pd.DataFrame(grid.cv_results_)
        self.set_params(estimator=grid.best_estimator_)
        return cv_results

    def fit(self, X, y, **fit_params):
        '''perform fit of estimator
        '''
        self.estimator.fit(X, y, **fit_params)
        return self

    def predit(self,
               X,
               pre_method='predict_proba',
               pre_level=False,
               pos_label=1,
               **kwargs):
        '''return predictions of estimator
        
        pre_method: str
            sklearn estimator method name: ['predict', predict_proba,
            decision_function]
        pre_level: bool
             if true, output score as integer rankings starting from 0
        pos_label
            index of predicted class
        '''
        estimator = self.estimator
        pre_func = getattr(estimator, pre_method)
        if pre_func is None:
            print('{} has no {} method'.format(
                _get_estimator_name(estimator), pre_method))
        y_pre = pre_func(X, **kwargs)
        if np.ndim(y_pre) > 1:
            y_pre = y_pre[:, pos_label]
        if pre_level:
            y_pre, bins = _binning(y_pre,
                                   bins=self.estimator.bins,
                                   labels=False)
        return y_pre

    def run_train(self,
                  train_set=None,
                  title='Train',
                  scoring=['roc_auc', 'KS'],
                  q=None,
                  bins=None,
                  max_leaf_nodes=None,
                  fit_params={},
                  cv=3,
                  save_fig=True,
                  **kwargs):
        '''
        - run train performance of an estimator; 
        - dump lift curve and ROC curve for train data under self.folder.path_; 
        - optionally dump spreadsheets of calculated data
        
        train_set: 
            2 element tuple, (X, y) of train data
        cv:
           n of cross validation folder, if cv==1, no cross validation        
        fit_params
            -other fit parameters of estimator
            
        return
        ----
        series: averaged train score for each scoring metrics

        '''
        L = locals().copy()
        L.pop('self')
        folder = self.folder
        # --
        title = title if title is not None else 0
        if train_set is None:
            train_set = self._get_dataset('.traindata')[0]
        else:
            folder.write(train_set, 'data/0.traindata')

        # trainning
        X = train_set[0]
        y = train_set[1]
        traincv = self.plot_auc_traincv(
            X, y, **get_kwargs(self.plot_auc_traincv, **L), **fit_params)

        self.fit(X, y, **fit_params)
        if any([max_leaf_nodes, q, bins]):
            lift_data = self.plot_lift(X, y, **get_kwargs(self.plot_lift, **L),
                                       **kwargs)
            lift = lift_data[-1]
        else:
            lift = pd.DataFrame()
            

        cv_score = self.cv_validate(X, y, **get_kwargs(self.cv_validate, **L),
                                    **kwargs)
        if self.verbose > 0:
            print('train data & cv_score & cv_splits data are being saved...')
            folder.write([lift, cv_score],
                         'spreadsheet/TrainPerfomance{}.xlsx'.format(title),
                         sheet_name=['liftcurve', 'train_score'])
            folder.write(traincv[-1],
                         'spreadsheet/TrainSplits{}.xlsx'.format(title))
        fig = plotter_score_path(cv_score, title='TrainScore_path')
        if save_fig is True:
            folder.write(fig, 'plots/TrainScore_path.pdf')
            plt.close()
        return cv_score.mean()

    def run_test(self,
                 test_set=None,
                 title=None,
                 use_self_bins=True,
                 cv=3,
                 scoring=['roc_auc', 'KS', 'average_precision'],
                 save_fig=True,
                 **kwargs):
        '''
        - run test performance of an estimator; 
        - dump lift curve and ROC curve for test data under self.folder.path_; 
        - optionally dump spreadsheets of calculated data
        
        test_set:
            2 element tuple (X_test, y_test) or list of them
        title:
            title for test_set indicator
        
        return
        ----
            series: averaged scoring for each of scoring metrics
        '''
        L = locals().copy()
        L.pop('self')
        L.pop('title')
        folder = self.folder
        # --

        r = 0
        if test_set is None:
            test_set, title = self._get_dataset('.testdata')[0]
            r -= 1

        test_set_list = get_flat_list(test_set)
        if title is not None:
            title_list = get_flat_list(title)
        else:
            title_list = [str(i) for i in range(len(test_set_list))]
        check_consistent_length(test_set_list, title_list)
        if r == 0:
            folder.write([test_set_list, title_list],
                         'data/{}.testdata'.format(len(title_list)))

        testscore = []
        for i, j in zip(test_set_list, title_list):
            # test performance
            X_test = i[0]
            y_test = i[1]
            # plot test auc
            testcv = self.plot_auc_test(X_test,
                                        y_test,
                                        title=j,
                                        **get_kwargs(self.plot_auc_test, **L,
                                                     **kwargs))
            # plot lift curve
            test_lift = self.plot_lift(X_test,
                                       y_test,
                                       title=j,
                                       **get_kwargs(self.plot_lift, **L),
                                       **kwargs)
            # test scores
            scores = self.test_score(X_test, y_test, cv=cv, scoring=scoring)
            scores['group'] = str(j)
            testscore.append(scores)
            if self.verbose > 0:
                print(
                    'test cv_score & cv_splits test data are being saved... ')
                folder.write(testcv[-1],
                             file='spreadsheet/TestSplits{}.xlsx'.format(j))
                if test_lift is None: 
                    lift=pd.DataFrame()
                else:
                    lift = test_lift[-1]
                folder.write(
                    [lift, scores],
                    sheet_name=['lift_curve', 'test_score'],
                    file='spreadsheet/TestPerfomance{}.xlsx'.format(j))

        testscore_all = pd.concat(testscore, axis=0, ignore_index=True)
        fig = plotter_score_path(testscore_all, title='score_path')
        if save_fig is True:
            folder.write(fig, 'plots/TestScore_path.pdf')
            plt.close()
        if self.verbose > 0 and len(testscore) > 1:
            folder.write(testscore_all, 'spreadsheet/TestPerformanceAll.xlsx')

        return testscore_all[scoring].mean()

    def run_sensitivity(self,
                        train_set=None,
                        title=None,
                        param_grid=-1,
                        refit='roc_auc',
                        scoring=['roc_auc', 'KS'],
                        fit_params={},
                        n_jobs=2,
                        save_fig=True,
                        **kwargs):
        '''
        - run sensitivity of param_grid (if param_grid=-1, use pre-difined); 
        - update self estimator as best estimator, & update self gridcv_results;
        - dump plots/spreadsheets
        
        parmameters
        ----
        train_set: 
            2 element tuple, (X, y) of train data
        param_grid:
            parameter grid space, if -1, use pipe_grid() to return predifined 
            param_grid
        **kwargs:
            GridSearchCV keywords
        '''

        L = locals().copy()
        L.pop('self')
        L.pop('param_grid')
        folder = self.folder
        #--
        if train_set is None:
            train_set = self._get_dataset('.traindata')[0]
        else:
            folder.write(train_set, 'data/0.traindata')

        if param_grid is -1:
            param_grid = []
            for k, v in self.estimator.named_steps.items():
                grid = pipe_grid(k)
                if grid is not None:
                    param_grid.extend(grid)

        if len(param_grid) == 0:
            print('no param_grid found, skip grid search')
            return

        # memory cache
        if hasattr(self.estimator, 'memory'):
            self.estimator.memory = os.path.relpath(
                os.path.join(self.folder.path_, 'tempfolder'))

        X, y = train_set
        cv_results = []
        for i, grid in enumerate(get_flat_list(param_grid)):
            self.grid_searchcv(X,
                               y=y,
                               param_grid=grid,
                               **get_kwargs(self.grid_searchcv, **L),
                               **kwargs)
            self.plot_gridcv(save_fig=save_fig, title=str(i))
            cv_results.append(self.gridcv_results)

        print('sensitivity results are being saved... ')
        title = 0 if title is None else str(title)
        folder.write(cv_results,
                     'spreadsheet/GridcvResults{}.xlsx'.format(title))
        self.save()
        self._shut_temp_folder()

    def run_analysis(self,
                     train_set,
                     test_set=None,
                     test_title=None,
                     max_leaf_nodes=None,
                     q=None,
                     bins=None,
                     cv=3,
                     grid_search=True,                    
                     train_test=True,
                     scoring=['roc_auc', 'KS'],
                     ):
        '''run analysis of estimator
        
        1. run self.run_sensitivity(if grid_search=True)
        2. run self.run_train,
        3. run self.run_test,
        4. store self trainscore & testscore
        
        train_set:
            (X, y) tuple to use as train set
        
        test_set:
            (X_test, y_test) tuple to use as test set
        
        cv:
            n_splits for cross validation
       
        grid_search bool:
            if True, perform grid_search
        
        train_test bool:
            if True, perform run_train & run_test
        
        q
            - number of equal frequency 
        bins
            - number of equal width or array of edges
        max_leaf_nodes
            - if not None perform supervised cutting, 
            - number of tree nodes using tree cut        
        .. note ::
            either of q, bins, max_leaf_nodes can be input, if all None,
            no lift curve plot
        
        return
        ------
            self instance
        
        '''
        if grid_search:
            self.run_sensitivity(train_set, scoring=scoring)
        
        if train_test:
            self.trainscore = self.run_train(train_set,
                                             cv=cv,
                                             q=q,
                                             bins=bins,
                                             max_leaf_nodes=max_leaf_nodes)
            print('cv score = \n', self.trainscore, '\n')
    
            if test_set is None:
                print('no test_set, skip run_test method ...\n')
            else:
                self.testscore = self.run_test(test_set,
                                               title=test_title,
                                               cv=cv,
                                               use_self_bins=True)
                print(self.testscore, '\n')
            
        self.save()
        
        return self

    def save(self):
        '''save current estimator instance, self instance 
        and self construction settings
        '''
        folder = self.folder
        # save esimator
        folder.write(self.estimator,
                     _get_estimator_name(self.estimator) + '.pipe')
        # save parameters
        folder.write(self.get_params(False),
                     self.__class__.__name__ +'.param')
        # save instance
        folder.write(
            self, self.__class__.__name__ +
            _get_estimator_name(self.estimator) + '.instance')

    def delete_model(self):
        '''delete self.folder.path_ folder containing model
        '''
        del self.folder.path_

    @property
    def feature_names(self):  #need update
        '''get input feature names of final estimator
        '''
        return selected_fearturename(self.estimator)

@dedent  
@Appender(ML_model.run_analysis.__doc__)
def run_analy(X, y, test_set=None, model_list=None, verbose=0, 
              dirs='analyzed_models', **kwargs):
    '''run analysis of a series of pre-defined models as returned by 
    get_default_estimators()
    
    dirs - str:
        directory to dump analyzed models
        
    return 
    ------
    
    - trainscore DataFrame 
    - testscore  DataFrame 
        
        averaged scores for each of metrics and each of estimators
    
    **kwargs 
        see ML_model.run_analysis() method
    
    Appended
    ----
    
    '''
    # --
    if model_list is None:
        l = get_default_estimators()
    else:
        l = model_list
    trainscore = []
    testscore = []
    for i in l:
        path = os.path.join(dirs, i)
        model = ML_model(i, path, verbose=verbose)
        model.run_analysis((X, y), test_set, **kwargs)       
        
        print("\n '{}' complete".format(i))
        if hasattr(model, 'testscore'):
            score = model.testscore.copy()
            score['pipe_testset'] = i
            testscore.append(score)
        if hasattr(model, 'trainscore'):
            score = model.trainscore.copy()
            score['pipe_trainset'] = i
            trainscore.append(score)
    
    if len(trainscore) > 0:
        trainscore = pd.concat(trainscore, axis=1, ignore_index=True).T
    if len(testscore) > 0 :
        testscore = pd.concat(testscore, axis=1, ignore_index=True).T
                
    return trainscore, testscore

def run_CVscores(X=None,
                 y=None,
                 cv=3,
                 scoring=['roc_auc', 'KS'],
                 estimator_lis=None):
    ''' return CV scores of a series of pre-defined piplines as returned by
    get_default_estimators()
    
    return
    -------
    dataframe 
        - cv scores of each pipeline
    '''
    if estimator_lis is None:
        l = get_default_estimators()
    else:
        l = estimator_lis

    if X is None:
        return set(l)
    else:
        lis = []
        for i in l:
            m = ML_model(estimator=i)
            scores = m.cv_validate(X, y, cv=cv, scoring=scoring).mean()
            scores['pipe'] = i
            lis.append(scores)
        return pd.concat(lis, axis=1, ignore_index=True).T


def _reset_index(*array):
    '''reset_index for df or series, return list of *arrays
    '''
    rst = []
    for i in array:
        if isinstance(i, (pd.DataFrame, pd.Series)):
            rst.append(i.reset_index(drop=True))
        else:
            rst.append(i)
    return rst


def _split_cv(*arrays, y=None, groups=None, cv=3, random_state=None):
    '''supervise splitting
    
    y
        - class label,if None not to stratify
    groups
        - split by groups
    cv
        - number of splits

    return
    ----
    generator of list containing splited arrays,shape = [m*n*k], for 1 fold
    [(0train, 0test), (1train, 1test), ...]

    m - indices of folds [0 : cv-1]
    n - indice of variable/arrays [0 : n_arrays-1]
    k - indice of train(0)/test[1] set [0:1]
    '''

    n_arrays = len(arrays)
    if n_arrays == 0:
        raise ValueError("At least one array required as input")
    validation.check_consistent_length(*arrays, y, groups)
    arrays = list(arrays)

    if cv == 1:
        if y is not None:
            arrays.append(y)
        return [[(i, i) for i in arrays]]
    # get cross validator
    if y is not None:
        arrays.append(y)
        cv = _split.check_cv(cv, y=y, classifier=True)
    else:
        cv = _split.check_cv(cv, classifier=False)
    # set random state
    if hasattr(cv, 'random_state'):
        cv.random_state = random_state
    # reset_index pandas df or series
    arrays = _reset_index(*arrays)
    arrays = _split.indexable(*arrays)
    # get indexing method
    safe_index = _split.safe_indexing
    train_test = ([
        (safe_index(i, train_index), safe_index(i, test_index)) for i in arrays
    ] for train_index, test_index in cv.split(arrays[0], y, groups))

    return train_test


def _get_estimator_name(estimator):
    '''return estimator's class name
    '''
    if hasattr(estimator, '_final_estimator'):
        estimator = estimator._final_estimator
    if hasattr(estimator, '__class__'):
        return estimator.__class__.__name__
    else:
        raise TypeError('estimator is not an valid sklearn estimator')


def _get_splits_combined(xy_splits, ret_type='test'):
    '''return list of combined X&y DataFrame for cross validated test set
    '''
    data_splits_test = [
        pd.concat((pd.DataFrame(i[1]) for i in item), axis=1)
        for item in xy_splits
    ]

    data_splits_train = [
        pd.concat((pd.DataFrame(i[0]) for i in item), axis=1)
        for item in xy_splits
    ]

    if ret_type == 'test':
        return data_splits_test
    if ret_type == 'train':
        return data_splits_train

  
def get_default_estimators(estimators='pipe'):
    '''return default list of estimators
    '''
    if estimators == 'pipe':
        estimators_lis = [
            # linear models
            'cleanNA_woe5_LogisticRegression',  
            'cleanNA_woe5_cleanNN_frf_LogisticRegression',                      
            'cleanNA_woe8_frf_LogisticRegression',
            'cleanNA_woeq8_cleanNN_frf_LogisticRegression',           
            'cleanNA_woe8_frf20_LogisticRegression',
            'cleanNA_woe5_cleanNN_fRFE10log_LogisticRegression',
            'cleanNA_woe5_runder_LinearSVC', 
            
            # default SVM, grid search log/hinge/huber/perceptron
            'cleanNA_woe5_Nys_SGDClassifier',
            'cleanNA_woe8_runder_Nys_frf_SGDClassifier',
            'cleanMean_oht_stdscale_frf_Nys_SGDClassifier',
            
            # tree based models
            'clean_oht_XGBClassifier',
            'clean_oht_cleanNN_fxgb_XGBClassifier',
            'clean_oht_cleanNN_inlierForest_fxgb_XGBClassifier',
            'clean_oht_cleanNN_fxgb_HistGradientBoostingClassifier',
            
            'clean_oht_frf_RandomForestClassifier',
            'clean_oht_cleanNN_RandomForestClassifier',
            'clean_oht_fxgb_BalancedRandomForestClassifier',
            'clean_oht_cleanNN_frf_AdaBoostClassifier',
            'clean_oht_fxgb_RUSBoostClassifier',
            'clean_oht_fxgb_cleanNN_GradientBoostingClassifier',
            'clean_oht_fsvm_cleanNN_GradientBoostingClassifier',
            'clean_oht_fxgb_DecisionTreeClassifier',
            'clean_oht_fxgb_runder_DecisionTreeClassifier',
        ]
    elif estimators == 'clf':
        estimators_lis = [
                'LogisticRegression',
                'LinearDiscriminantAnalysis',
                'XGBClassifier',
                'RandomForestClassifier',
                'BalancedRandomForestClassifier',
                'AdaBoostClassifier',
                'RUSBoostClassifier',
                'GradientBoostingClassifier',
                'DecisionTreeClassifier',
                'KNeighborsClassifier',
                'HistGradientBoostingClassifier',
                ]
    return estimators_lis