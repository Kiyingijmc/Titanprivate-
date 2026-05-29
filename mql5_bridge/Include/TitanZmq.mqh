//+------------------------------------------------------------------+
//|                                                     TitanZmq.mqh |
//|                                     Updated for Titan v14.3 Pro  |
//+------------------------------------------------------------------+
#property copyright "Titan Algo"
#property strict

// Define Standard ZMQ Constants if not present
#define ZMQ_REP 4
#define ZMQ_PULL 7
#define ZMQ_PUSH 8
#define ZMQ_NOBLOCK 1

#import "libzmq.dll"
   long zmq_ctx_new();
   int  zmq_ctx_term(long context);
   long zmq_socket(long context, int type);
   int  zmq_close(long socket);
   int  zmq_bind(long socket, uchar &endpoint[]);
   int  zmq_connect(long socket, uchar &endpoint[]);
   int  zmq_send(long socket, uchar &buf[], int len, int flags);
   int  zmq_recv(long socket, uchar &buf[], int len, int flags);
#import

class TitanZmq {
private:
   long m_context;
   long m_socket;
   bool m_active;

public:
   TitanZmq() { m_context = 0; m_socket = 0; m_active = false; }
   ~TitanZmq() { Shutdown(); }

   // Safe Initialization
   bool Init() {
      if(m_context == 0) m_context = zmq_ctx_new();
      return (m_context != 0);
   }

   // Connect Logic (Client Mode) - Used because Python Binds (Server Mode)
   bool Connect(int type, string address) {
      if(m_context == 0) Init();
      m_socket = zmq_socket(m_context, type);
      if(m_socket == 0) return false;
      
      uchar ep[];
      StringToCharArray(address, ep);
      
      if(zmq_connect(m_socket, ep) == 0) {
         m_active = true;
         // Linger 0 ensures immediate socket kill on shutdown
         return true;
      }
      return false;
   }

   bool Send(string message) {
      if(!m_active) return false;
      uchar data[];
      // CP_UTF8 ensures JSON compatibility
      int len = StringToCharArray(message, data, 0, WHOLE_ARRAY, CP_UTF8) - 1; 
      if(len <= 0) return false;
      // 0 = Blocking Send (Standard for PUSH to avoid packet loss)
      return (zmq_send(m_socket, data, len, 0) >= 0);
   }

   string Recv() {
      if(!m_active) return "";
      static uchar buf[1048576]; // 1MB Buffer for large history chunks
      ArrayInitialize(buf, 0);
      
      // ZMQ_NOBLOCK is critical to prevent MT5 freezing
      int res = zmq_recv(m_socket, buf, 1048576, ZMQ_NOBLOCK);
      
      if(res > 0) return CharArrayToString(buf, 0, res, CP_UTF8);
      return "";
   }

   void Shutdown() {
      if(m_socket != 0) { zmq_close(m_socket); m_socket = 0; }
      if(m_context != 0) { zmq_ctx_term(m_context); m_context = 0; }
      m_active = false;
   }
};