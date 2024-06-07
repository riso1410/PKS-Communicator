import socket
import os
import threading
import binascii
import time
import math
import struct
import numpy as np

#FLAG 1 - ACK | 2 - KEEP ALIVE | 3 - DATA | 4 - ACCEPTED | 5 - RESEND | 6 - LAST PACKET | 7 - SWITCH | 8 - FINISH | 1B
#PACKET NUM | 2B
#CRC | 2B
#DATA | 0 - 1467B

SERVER_CONSOLE_THREAD = False # global variable for server console thread
THREAD_KEEP_ALIVE = False # global variable for keep_alive status
HEADER_SIZE = 5 # size of header in bytes
BUFFER_SIZE = 1500 # size of buffer in bytes 


#----------------------------------------------COMMON-------------------------------------------------#
# method for calculating crc
def calculate_crc(packet, error_rate):

    crc_value = binascii.crc_hqx(packet, 0)

    if np.random.choice([True, False], p=[error_rate, 1-error_rate]): # user defined error rate as probability
        crc_value += 1 
        
    return crc_value


# method for creating header without data
def create_header(flag='0', packet_num=0, data=b'', file_name=None, error_rate=0.0):
    
    # create the header
    header = struct.pack('c', str.encode(flag))  # Flag
    header += struct.pack('H', packet_num)  # Packet number

    crc = calculate_crc(header + data, error_rate)

    if file_name:   # if sending file name
        crc = calculate_crc(header + file_name, error_rate)

    header += struct.pack('H', crc)  
    return header


#method for unpacking header and data when they are received
def unpack_header(packet):

    flag = struct.unpack('c', packet[:1])
    packet_num = struct.unpack('H', packet[1:3])
    crc = struct.unpack('H', packet[3:5])
    data = packet[5:]

    flag = flag[0].decode()
    packet_num = packet_num[0]
    crc = crc[0]
    return flag, packet_num, crc, data


def check_size(data, frag_size):
    data_length = len(data)
    minimal_size = math.ceil(int(data_length / 65535))
    # check if data size can fit into 65,535 packets
    if data_length / frag_size < 65535:
        return frag_size
    
    else:
        try:
            frag_size = int(input(f'Fragment size too small. Enter fragment size (min {minimal_size + 1} - max {BUFFER_SIZE - HEADER_SIZE - 28} B): '))
        except:
            print("MAX transfer size set")
            frag_size = BUFFER_SIZE - HEADER_SIZE - 28
        return check_size(data, frag_size)


#----------------------------------------------THREADS-------------------------------------------------#
# method on server side for console running on thread
def server_console(server_socket, client_addr):

    global SERVER_CONSOLE_THREAD

    while SERVER_CONSOLE_THREAD:

        print("Choose from: switch (1) | exit (2)")
        task = input(">> ")

        if task in ["switch", "1"]:
            server_socket.sendto(create_header('7'), client_addr)
            return

        elif task in ["exit", "2"]:
            server_socket.sendto(create_header('8'), client_addr)
            return

        else:
            print("Invalid input")


# method on client side for running keep_alive on thread when data are sent
def keeping_alive(client_socket, server_addr):
    
    global THREAD_KEEP_ALIVE

    failed_attempts = 0
    
    while THREAD_KEEP_ALIVE and failed_attempts < 3:
        
        countdown = 5*(failed_attempts+1) # countdown for response increases with each failed attempt

        try:
            client_socket.sendto(create_header('2'), server_addr)
            
            client_socket.settimeout(countdown)
            _, server_addr = client_socket.recvfrom(BUFFER_SIZE)
            print("Keeping alive...")
            failed_attempts = 0
            time.sleep(countdown) # waiting for countdown to end before trying again
    
        except socket.timeout:
            failed_attempts += 1
            print(f"Server did not respond ({failed_attempts}/3)")
        
        except Exception as e:
            print("Error:", e)
            THREAD_KEEP_ALIVE = False
            client_socket.close()
            os._exit(0)
                
    if failed_attempts >= 3:
        print(f"Server did not respond {failed_attempts} times. \nExiting...")
        THREAD_KEEP_ALIVE = False
        client_socket.close()
        os._exit(0)


#----------------------------------------------SERVER-------------------------------------------------#
def server_setup():
    
    while True:
        try:
            server_port = int(input("Enter server port: "))
            break

        except:
            print("Invalid input")
            continue
    
    server_addr = socket.gethostbyname(socket.gethostname()) #getting pc ip address

    #creating socket
    server_socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
    server_socket.bind((server_addr, server_port))
    print(f'Server is running on {server_addr}:{server_port}')

    try:
        server_socket.settimeout(60)  # timeout waiting for client to connect
        _, client_addr = server_socket.recvfrom(BUFFER_SIZE)
        server_socket.sendto(create_header('1'), client_addr) # ack to client
        print(f'Client {client_addr} connected')
        server(server_socket, client_addr)

    except socket.error as e:
        print("Server not found. Error:", e)
        server_socket.close()


# main server logic for listening to client
def server(server_socket, client_addr):

    global SERVER_CONSOLE_THREAD
    rec_data = [] # buffer for received data
    packet_num_list = [] # list of received packet numbers
    total_length = 0 # total length of received data
    file_name = None
    
    SERVER_CONSOLE_THREAD = True # flag to keep server console running
    threading.Thread(target=server_console, args=(server_socket, client_addr), daemon=True).start() # thread for console

    while True:

        try:
            server_socket.settimeout(40) # timeout until client chooses an action
            data, client_addr = server_socket.recvfrom(BUFFER_SIZE)

            flag, packet_num, crc, data = unpack_header(data)
            
            #calculate crc
            header = struct.pack('c', str.encode(flag))  
            header += struct.pack('H', packet_num)  
            new_crc = calculate_crc(header + data, 0.0)

            #ack flag
            if flag == '1':
                server_socket.sendto(create_header('1'), client_addr)
                print(f'Client {client_addr} connected')

            #keep alive flag
            elif flag == '2':
                server_socket.sendto(create_header('2'), client_addr)
                print("Keeping alive...")

            #data flag
            elif flag == '3':
                SERVER_CONSOLE_THREAD = False

                if packet_num in packet_num_list: # if packet is duplicate
                    continue

                if crc == new_crc:
                    packet_num_list.append(packet_num) 
                
                if file_name is None and packet_num == 0:
                    if crc == new_crc:
                        file_name = data.decode()
                        print(f'File name: {file_name}')
                        server_socket.sendto(create_header('4'), client_addr)
                
                else:
                    data = receive(server_socket, client_addr, new_crc, packet_num, crc, data, file_name)
                    rec_data.append(data)
                    if data:
                        total_length += len(data)

            #finished sending flag
            elif flag == '6':
                final_data(rec_data, total_length, file_name)
                server_socket.sendto(create_header("6"), client_addr)
                rec_data = []
                packet_num_list = []
                total_length = 0
                file_name = None
                SERVER_CONSOLE_THREAD = True
                threading.Thread(target=server_console, args=(server_socket, client_addr), daemon=True).start() 
            
            #switch flag
            elif flag == '7':
                SERVER_CONSOLE_THREAD = False
                client(server_socket, client_addr)
                return 

            #terminate flag
            elif flag == '8':
                SERVER_CONSOLE_THREAD = False
                server_socket.close()
                print("Exiting...")
                break

        except socket.timeout:
            print("Client not responding")
            SERVER_CONSOLE_THREAD = False
            server_socket.close()
            break
    

# decoding data and checking crc
def receive(server_socket, addr, new_crc, packet_num, crc, data, file_name):
    
    if crc == new_crc:

        # if file name is received (in first packet when sending a file)
        if file_name is None:
            rec_data = data.decode()

        else:
            rec_data = data

        server_socket.sendto(create_header('4'), addr) # send positive ack to client
        print(f'Packet {packet_num} accepted | Data size: {len(data)}')
        return rec_data
        
    else:
        server_socket.sendto(create_header('5'), addr) # send negative ack to client
        print(f'Packet {packet_num} discarded')
        return None


# whole data received - printing or saving to file
def final_data(rec_data, total_length, file_name=None):
    
    rec_data = [frag for frag in rec_data if frag is not None] # removing None values from list (when packet is discarded)

    if file_name is None: # if message
        print("Message: " + ''.join(rec_data))
        print(f'Message size: {total_length} B')

    else: # if file
        with open(file_name, 'wb') as file:
            for frag in rec_data:
                file.write(frag)
        file.close()

        print(f'Absolute path to {file_name}: {os.path.abspath(file_name)}')
        print(f'File size: {os.path.getsize(file_name)} B')


#----------------------------------------------CLIENT-------------------------------------------------#
def client_setup():

    while True:
        try:
            server_ip = input("Enter server address: ")
            server_port = int(input("Enter server port: "))
            break

        except:
            print("Invalid input")
            continue

    server_addr = (server_ip, server_port)
    client_socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)

    # trying to connect to server
    try:
        client_socket.sendto(create_header('1'), server_addr)
        data, server_addr = client_socket.recvfrom(BUFFER_SIZE)
        flag = data[:1].decode()

        if flag == '1':
            print(f'Established connection with {server_addr}')
            client(client_socket, server_addr)
    
    except socket.timeout:
        print("Server not responding")
        client_socket.close()
        return

    except socket.error as e:
        print("Server not found. Error:", e)
        client_socket.close()
        return


# main client logic for inputs
def client(client_socket, server_addr):
    
    global THREAD_KEEP_ALIVE 

    while True:
        print("Choose from: message (1) | file (2) | switch (3) | exit (4) | listen (5)")
        task = input(">> ")

        if task in ["message","1"]:
            THREAD_KEEP_ALIVE = False
            prep_for_send(client_socket, server_addr, "message")
            THREAD_KEEP_ALIVE = True
            # thread for keeping connection alive after sending data
            threading.Thread(target=keeping_alive, args=(client_socket, server_addr), daemon=True).start() 

        elif task in ["file","2"]:
            THREAD_KEEP_ALIVE = False
            prep_for_send(client_socket, server_addr, "file")
            THREAD_KEEP_ALIVE = True
            # thread for keeping connection alive after sending data
            threading.Thread(target=keeping_alive, args=(client_socket, server_addr), daemon=True).start() 

        elif task in ["switch","3"]:
            # send flag to server to switch
            client_socket.sendto(create_header('7'), server_addr)
            THREAD_KEEP_ALIVE = False
            server(client_socket, server_addr)
            return

        elif task in ["exit","4"]:
            #send flag to exit
            client_socket.sendto(create_header('8'), server_addr)
            # turn off keep_alive thread
            THREAD_KEEP_ALIVE = False
            break

        elif task in ["listen","5"]:
            THREAD_KEEP_ALIVE = False

            try:
                # wait for server to send task for 15 seconds
                client_socket.settimeout(15)
                response, server_addr = client_socket.recvfrom(BUFFER_SIZE)
                flag = response[:1].decode()

                # switch flag
                if flag == '7':
                    client_socket.sendto(create_header('7'), server_addr)
                    THREAD_KEEP_ALIVE = False
                    server(client_socket, server_addr)
                    return

                # terminate flag
                elif flag == '8':
                    client_socket.sendto(create_header('8'), server_addr)
                    print("Connection terminated")
                    break
            
            except:
                THREAD_KEEP_ALIVE = True
                threading.Thread(target=keeping_alive, args=(client_socket, server_addr), daemon=True).start() 
                print("No task from server")

        else:
            print("Invalid input")
        

# setting fragment size and error rate
def prep_for_send(client_socket, server_socket, task):
    
    while True:
        try:
            frag_size = int(input(f'Enter fragment size (min {1} - max {BUFFER_SIZE - HEADER_SIZE - 28} B): '))
            if 0 < frag_size <= BUFFER_SIZE - HEADER_SIZE - 28:
                break
            else:
                print("Invalid fragment size")
        except ValueError:
            print("Invalid input. Please enter a valid number.")

    while True:
        print("Error rate (0 - 0.8): ")
        try:
            error_rate = float(input(">> "))
        except:
            print("Invalid input")
            continue

        if error_rate >= 0 and error_rate <= 0.8:
            break

    if task == "message":
        print("Enter message: ")
        message = input(">> ")
        frag_size = check_size(message, frag_size)
        send_data(client_socket, server_socket, message, frag_size, error_rate)
    
    elif task == "file":
        print("Enter file path: ")
        file_path = input(">> ")
        file_path = file_path.replace('"', '')

        if os.path.isfile(file_path):
            file_name = os.path.basename(file_path)
            with open(file_path, 'rb') as f:
                data = f.read()

            frag_size = check_size(data, frag_size)
            send_data(client_socket, server_socket, data, frag_size, error_rate, file_name)


# main logic for sending data
def send_data(client_socket, server_addr, data, frag_size, error_rate, file_name=None):

    packet_num = 1
    print(f'Total size of data: {len(data)} B')
    
    # if sending file packet num 0 is for file name
    if file_name:
        packet = create_header('3', 0, file_name=str.encode(file_name))
        client_socket.sendto(packet + str.encode(file_name), server_addr)

        try:
            response, server_addr = client_socket.recvfrom(BUFFER_SIZE)
            flag = response[:1].decode()

            if flag != '4':
                print("Filename not received")
                return
            
        except:
            print("Server not responding")
            return

    total_packets = math.ceil(len(data) / frag_size)
    
    # sending data in packets
    while total_packets != 0:
        packet_data = data[:frag_size]

        # if sending message -> encode to bytes
        if file_name is None:
            packet_data = str.encode(packet_data)
        
        header = create_header('3', packet_num, packet_data, error_rate=error_rate)

        # send data to server
        client_socket.sendto(header + packet_data, server_addr)

        #receive response
        try:
            client_socket.settimeout(15)
            response, server_addr = client_socket.recvfrom(BUFFER_SIZE)
            flag = response[:1].decode()

        except:
            client_socket.sendto(header + packet_data, server_addr)
            try:
                client_socket.settimeout(15)
                response, server_addr = client_socket.recvfrom(BUFFER_SIZE)
                flag = response[:1].decode()
            except:
                print("Server not responding")
                client_socket.close()
                return

        # if packet is accepted send next packet
        if flag == '4':
            data = data[frag_size:]
            print(f"Packet {packet_num} sent | Data size: {len(packet_data)}")
            packet_num += 1
            total_packets -= 1

        # if packet is discarded resend packet
        elif flag == '5':
            print(f"Packet {packet_num} resending")
            continue
    
    # sending last packet with finish flag
    client_socket.sendto(create_header('6'), server_addr)
    
    try: 
        client_socket.settimeout(15)
        response, server_addr = client_socket.recvfrom(BUFFER_SIZE)
        flag = response[:1].decode()
    except:
        print("Could not reach server")

    print("Data sent")

#----------------------------------------------MENU-------------------------------------------------#
def main():

    while True:

        print("Choose from: client (1) | server (2) | exit (3)")
        task = input(">> ")

        if task in ["client","1"]:
            client_setup()

        elif task in ["server","2"]:
            server_setup()
            
        elif task in ["exit","3"]:
            return
        
        else:
            print("Invalid input")
        
        
if __name__ == '__main__':
    main()