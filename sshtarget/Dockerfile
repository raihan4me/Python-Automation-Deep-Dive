FROM ubuntu:24.04
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends openssh-server && rm -rf /var/lib/apt/lists/* && mkdir -p /run/sshd && rm -f /etc/ssh/ssh_host_*
RUN useradd -m -s /bin/bash opsuser
COPY authorized_keys /home/opsuser/.ssh/authorized_keys
RUN chown -R opsuser:opsuser /home/opsuser/.ssh && chmod 700 /home/opsuser/.ssh && chmod 600 /home/opsuser/.ssh/authorized_keys
RUN echo 'PasswordAuthentication no' > /etc/ssh/sshd_config.d/opskit.conf && echo 'PermitRootLogin no' >> /etc/ssh/sshd_config.d/opskit.conf
EXPOSE 22
CMD ["/bin/sh", "-c", "ssh-keygen -A && exec /usr/sbin/sshd -D -e"]
