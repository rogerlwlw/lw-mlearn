# -*- coding: utf-8 -*-
"""
Created on Mon Jun  3 14:10:59 2019

@author: rogerluo
"""
from lw_mlearn.lw_model import train_models
from lw_mlearn import pipe_main, ML_model
from sklearn.datasets import make_classification
from sklearn.gaussian_process.kernels import (RBF, Matern, RationalQuadratic,
                                              ExpSineSquared, DotProduct,
                                              Exponentiation, ConstantKernel)

def test_model():
    '''with small fake data to walk through workflow
    '''
    X, y = make_classification(300, n_redundant=5, n_features=30)
    l = [
         'clean_LDA_fxgb_cleanNN_AdaBoostClassifier',
#         'clean_oht_fRFElog_cleanNN_GaussianProcessClassifier',  
#         
#         'clean_oht_fxgb_cleanNN_XGBClassifier',
#         'clean_oht_fxgb_cleanNN_RandomForestClassifier',
#         'clean_oht_fxgb_cleanNN_GradientBoostingClassifier',
#         'clean_oht_fxgb_cleanNN_DecisionTreeClassifier',
#         'clean_oht_fxgb_cleanNN_BalancedRandomForestClassifier',
#         'clean_oht_fxgb_cleanNN_RUSBoostClassifier',        
#         'clean_oht_fRFElog_cleanNN_GradientBoostingClassifier',
         ]
    # --
    for i in l:        
        model = train_models(i, (X, y), (X, y), max_leaf_nodes=10)
        model.delete_model()
        
if __name__ == '__main__':
    test_model()  
