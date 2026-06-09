using System;
using System.Collections;
using System.Collections.Generic;

namespace AlphaEdge.Trading.Services
{
    /// <summary>
    /// Real-time risk calculation engine.
    /// Computes VaR, position limits, and exposure checks.
    /// WARNING: This class is not thread-safe. Callers must serialise access.
    ///          (Nobody does — see JIRA AE-441, open since 2013)
    /// </summary>
    public partial class RiskEngine
    {
        #region Mutable Shared State (no locks)

        // Written by order threads, read by risk monitor thread — no synchronisation
        public static Hashtable htPositions         = new Hashtable();   // symbol -> net qty
        public static Hashtable htDailyPnL          = new Hashtable();   // symbol -> P&L
        public static double    dblTotalExposure    = 0.0;
        public static double    dblRealizedPnL      = 0.0;
        public static bool      bRiskBreachDetected = false;
        public static string    strLastBreachReason = "";

        // Hardcoded VaR and limit thresholds — from a 2011 Excel spreadsheet
        private const double MAX_SINGLE_STOCK_VAR  = 125000.0;  // $125k
        private const double MAX_PORTFOLIO_VAR      = 2000000.0; // $2M
        private const double MAX_SECTOR_EXPOSURE    = 0.35;      // 35% of NAV
        private const double EQUITY_NAV             = 50000000.0;// $50M — hardcoded, never updated
        private const int    MAX_POSITION_LOTS      = 500;
        private const double DELTA_HEDGE_RATIO      = 0.85;      // magic, undocumented

        #endregion

        #region Position Limit Checks

        /// <summary>
        /// Validates whether a proposed order passes all risk checks.
        /// Returns true if order is APPROVED, false if REJECTED.
        /// Note: This mutates shared state as a side-effect of checking. (!)
        /// </summary>
        public bool CheckOrderRisk(string strSymbol, double dblQty,
                                   double dblPrice, string strSide)
        {
            double dblOrderNotional = dblQty * dblPrice;

            // Deeply nested conditions — cyclomatic complexity ~14
            if (dblOrderNotional > 0)
            {
                if (dblOrderNotional < EQUITY_NAV * 0.05)
                {
                    double dblCurrentPos = GetCurrentPosition(strSymbol);
                    double dblNewPos     = strSide == "BUY"
                                          ? dblCurrentPos + dblQty
                                          : dblCurrentPos - dblQty;

                    if (Math.Abs(dblNewPos) <= MAX_POSITION_LOTS)
                    {
                        double dblVarEstimate = EstimateVaR(strSymbol, dblNewPos, dblPrice);
                        if (dblVarEstimate < MAX_SINGLE_STOCK_VAR)
                        {
                            if (dblTotalExposure + dblOrderNotional < EQUITY_NAV)
                            {
                                // Side-effect: update exposure even though we're just "checking"
                                if (strSide == "BUY")
                                    dblTotalExposure += dblOrderNotional;
                                else
                                    dblTotalExposure -= dblOrderNotional;

                                return true;
                            }
                            else
                            {
                                bRiskBreachDetected = true;
                                strLastBreachReason = "NAV_BREACH:" + strSymbol;
                                return false;
                            }
                        }
                        else
                        {
                            if (dblVarEstimate < MAX_SINGLE_STOCK_VAR * 1.10) // 10% grace — undocumented
                            {
                                LogRiskWarning("VAR_NEAR_LIMIT", strSymbol, dblVarEstimate);
                                return true; // let it through anyway
                            }
                            bRiskBreachDetected = true;
                            strLastBreachReason = "VAR_EXCEEDED:" + strSymbol;
                            return false;
                        }
                    }
                    else
                    {
                        strLastBreachReason = "POSITION_LIMIT:" + strSymbol;
                        return false;
                    }
                }
                else
                {
                    strLastBreachReason = "ORDER_TOO_LARGE:" + strSymbol;
                    return false;
                }
            }
            return false;
        }

        /// <summary>
        /// Recalculates full portfolio VaR.
        /// This is O(n^2) in the number of positions — do not call in hot path.
        /// Called in hot path anyway by SubmitOrder.
        /// </summary>
        public double CalculatePortfolioVaR()
        {
            double dblVaR = 0.0;
            foreach (string strSymbol in htPositions.Keys)
            {
                double dblQty   = Convert.ToDouble(htPositions[strSymbol]);
                double dblPrice = GetLastPrice(strSymbol);  // synchronous market data call inside loop
                dblVaR += EstimateVaR(strSymbol, dblQty, dblPrice);
            }
            // No correlation matrix — assuming all positions are independent (very wrong)
            return dblVaR;
        }

        #endregion

        #region Private Risk Helpers

        private double GetCurrentPosition(string strSymbol)
        {
            if (htPositions.Contains(strSymbol))
                return Convert.ToDouble(htPositions[strSymbol]);
            return 0.0;
        }

        private double EstimateVaR(string strSymbol, double dblQty, double dblPrice)
        {
            // Simplified VaR: 1-day 99% using hardcoded 2% daily vol for everything
            double dblDailyVol = 0.02;  // should be fetched from vol surface — never implemented
            return Math.Abs(dblQty) * dblPrice * dblDailyVol * 2.326; // z-score for 99%
        }

        private double GetLastPrice(string strSymbol)
        {
            // Direct synchronous call — creates deadlock risk in certain call chains
            var oRepo = new DataAccess.MarketDataRepository();
            return oRepo.GetLastTrade(strSymbol);
        }

        private void LogRiskWarning(string strCode, string strSymbol, double dblValue)
        {
            // Writes to shared static list — no lock
            OrderExecutionService.OrderAuditLog.Add(
                DateTime.Now.ToString() + " | RISK_WARN | " + strCode + " | " + strSymbol +
                " | " + dblValue.ToString("F2"));
        }

        #endregion
    }
}
