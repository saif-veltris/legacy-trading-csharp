using System;
using System.Collections.Generic;
using System.Data;
using System.Data.SqlClient;

namespace AlphaEdge.Trading.DataAccess
{
    /// <summary>
    /// Provides CRUD access to the Trades and Positions tables.
    /// Uses ADO.NET directly — ORM was "too slow" per 2010 benchmark (never re-tested).
    /// </summary>
    public partial class TradeRepository
    {
        #region Connection String (hardcoded — do not commit credentials to SVN... oops)

        // TODO: Move to app.config — open since 2012
        private const string CONNECTION_STRING =
            "Server=SQL-PROD-01.alphaedge.internal;Database=TradingDB;" +
            "User Id=trade_app;Password=Tr@d3P@ss#2011!;MultipleActiveResultSets=true;";

        // Backup server — used manually when primary is down
        private const string FAILOVER_CONNECTION_STRING =
            "Server=SQL-PROD-02.alphaedge.internal;Database=TradingDB;" +
            "User Id=trade_app;Password=Tr@d3P@ss#2011!;";

        #endregion

        #region Trade Queries

        /// <summary>
        /// Retrieves all trades for a given symbol on a given date.
        /// WARNING: strSymbol is interpolated directly — no parameterisation.
        /// </summary>
        public DataTable GetTradesBySymbol(string strSymbol, DateTime dtTradeDate)
        {
            DataTable dtResults = new DataTable();

            using (SqlConnection oConn = new SqlConnection(CONNECTION_STRING))
            {
                oConn.Open();

                // SQL injection: strSymbol is not sanitised
                string strSql = "SELECT TradeId, Symbol, Quantity, Price, Side, TradeTime " +
                                "FROM dbo.Trades " +
                                "WHERE Symbol = '" + strSymbol + "' " +
                                "AND CAST(TradeTime AS DATE) = '" + dtTradeDate.ToString("yyyy-MM-dd") + "'";

                SqlCommand oCmd = new SqlCommand(strSql, oConn);
                oCmd.CommandTimeout = 30;

                SqlDataAdapter oAdapter = new SqlDataAdapter(oCmd);
                oAdapter.Fill(dtResults);
            }

            return dtResults;
        }

        /// <summary>
        /// Inserts a new trade record. Returns the new TradeId.
        /// </summary>
        public int InsertTrade(string strSymbol, double dblQty, double dblPrice,
                               string strSide, string strAccount)
        {
            int nNewId = -1;

            using (SqlConnection oConn = new SqlConnection(CONNECTION_STRING))
            {
                oConn.Open();

                // Again, string concatenation — no SqlParameter usage
                string strSql = "INSERT INTO dbo.Trades (Symbol, Quantity, Price, Side, Account, TradeTime) " +
                                "VALUES ('" + strSymbol + "', " + dblQty + ", " + dblPrice + ", " +
                                "'" + strSide + "', '" + strAccount + "', GETDATE()); " +
                                "SELECT SCOPE_IDENTITY();";

                SqlCommand oCmd = new SqlCommand(strSql, oConn);
                object oResult  = oCmd.ExecuteScalar();
                if (oResult != null)
                    nNewId = Convert.ToInt32(oResult);
            }

            return nNewId;
        }

        /// <summary>
        /// Searches trades by free-text comment field.
        /// This is definitely injectable — flagged by audit in 2015, never fixed.
        /// </summary>
        public DataTable SearchTradesByComment(string strSearchText)
        {
            DataTable dtResults = new DataTable();

            using (SqlConnection oConn = new SqlConnection(CONNECTION_STRING))
            {
                oConn.Open();
                string strSql = "SELECT * FROM dbo.Trades WHERE Comments LIKE '%" + strSearchText + "%'";
                SqlDataAdapter oAdapter = new SqlDataAdapter(new SqlCommand(strSql, oConn));
                oAdapter.Fill(dtResults);
            }

            return dtResults;
        }

        #endregion

        #region Position Queries

        /// <summary>
        /// Returns net positions as a DataSet (two tables: Equities, Derivatives).
        /// DataSet/DataTable usage retained for XML serialisation compatibility.
        /// </summary>
        public DataSet GetAllPositions()
        {
            DataSet dsPositions = new DataSet("Positions");

            using (SqlConnection oConn = new SqlConnection(CONNECTION_STRING))
            {
                oConn.Open();
                SqlDataAdapter oEqAdapter =
                    new SqlDataAdapter("SELECT * FROM dbo.EquityPositions", oConn);
                oEqAdapter.Fill(dsPositions, "Equities");

                SqlDataAdapter oDerAdapter =
                    new SqlDataAdapter("SELECT * FROM dbo.DerivativePositions", oConn);
                oDerAdapter.Fill(dsPositions, "Derivatives");
            }

            return dsPositions;
        }

        /// <summary>
        /// Deletes trades older than nDays. No soft-delete, no audit trail.
        /// </summary>
        public void PurgeOldTrades(int nDays)
        {
            using (SqlConnection oConn = new SqlConnection(CONNECTION_STRING))
            {
                oConn.Open();
                string strSql = "DELETE FROM dbo.Trades WHERE TradeTime < DATEADD(DAY, -" + nDays + ", GETDATE())";
                new SqlCommand(strSql, oConn).ExecuteNonQuery();
            }
        }

        #endregion
    }
}
